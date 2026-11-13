import hashlib

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from y_py import (
    YDoc,
    apply_update,
    encode_state_as_update,
    encode_state_vector,
)

from editor.models import (
    DocumentSnapshot,
    DocumentUpdate,
    FileEntry,
    WorkspaceMembership,
)


MAX_WEBSOCKET_MESSAGE_BYTES = 1_000_000
UPDATE_COMPACTION_THRESHOLD = 100
UPDATE_RETENTION_LIMIT = 100


def _apply_yjs_update(document, update):
    try:
        apply_update(document, update)
    except Exception as error:
        if type(error).__module__ != "y_py" or type(error).__name__ != "EncodingException":
            raise
        raise ValueError("Invalid Yjs update") from error


def _encode_yjs_state(document, state_vector, error_message):
    try:
        return encode_state_as_update(document, state_vector)
    except Exception as error:
        if type(error).__module__ != "y_py" or type(error).__name__ != "EncodingException":
            raise
        raise ValueError(error_message) from error


def _read_var_uint(data, offset):
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 49:
            raise ValueError("Invalid Yjs message")
    raise ValueError("Incomplete Yjs message")


def _read_var_bytes(data, offset):
    length, offset = _read_var_uint(data, offset)
    end = offset + length
    if end > len(data):
        raise ValueError("Incomplete Yjs message")
    return data[offset:end], end


def _write_var_uint(value):
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _sync_message(sync_type, payload):
    return (
        _write_var_uint(0)
        + _write_var_uint(sync_type)
        + _write_var_uint(len(payload))
        + payload
    )


class EditorConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user", AnonymousUser())
        document_id = self.scope["url_route"]["kwargs"]["room_name"]
        access = await self._document_access(document_id, user)
        if access is None:
            await self.close(code=4403)
            return

        self.document_id, self.role = access
        self.room_group_name = f"editor_{self.document_id}"
        self.user_group_name = f"editor_user_{user.id}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

    async def receive(self, bytes_data=None, text_data=None):
        if bytes_data is None or len(bytes_data) > MAX_WEBSOCKET_MESSAGE_BYTES:
            await self.close(code=4400)
            return
        try:
            message_type, offset = _read_var_uint(bytes_data, 0)
            if not await self._refresh_access():
                return

            if message_type == 0:
                sync_type, offset = _read_var_uint(bytes_data, offset)
                payload, end = _read_var_bytes(bytes_data, offset)
                if end != len(bytes_data):
                    raise ValueError("Unexpected data after Yjs message")
                if sync_type == 0:
                    await self._send_sync_state(payload)
                elif sync_type in (1, 2):
                    if self.role == WorkspaceMembership.Role.VIEWER:
                        return
                    _apply_yjs_update(YDoc(), payload)
                    created = await self._persist_update(payload)
                    if created:
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                "type": "editor_message",
                                "bytes_data": _sync_message(2, payload),
                                "source_channel": self.channel_name,
                            },
                        )
                else:
                    raise ValueError("Unsupported Yjs sync message")
                return

            if message_type == 1:
                _, end = _read_var_bytes(bytes_data, offset)
                if end != len(bytes_data):
                    raise ValueError("Unexpected data after awareness message")
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "editor_message",
                        "bytes_data": bytes_data,
                        "source_channel": self.channel_name,
                    },
                )
                return

            if message_type == 3 and offset == len(bytes_data):
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "editor_message",
                        "bytes_data": bytes_data,
                        "source_channel": self.channel_name,
                    },
                )
                return

            raise ValueError("Unsupported Yjs message")
        except ValueError:
            await self.close(code=4400)

    async def editor_message(self, event):
        if event.get("source_channel") != self.channel_name:
            await self.send(bytes_data=event["bytes_data"])

    async def editor_access_changed(self, event):
        access = await self._document_access(
            self.document_id, self.scope.get("user", AnonymousUser())
        )
        if access is None:
            await self.close(code=4403)
            return
        self.document_id, self.role = access

    async def _refresh_access(self):
        access = await self._document_access(
            self.document_id, self.scope.get("user", AnonymousUser())
        )
        if access is None:
            await self.close(code=4403)
            return False
        self.document_id, self.role = access
        return True

    async def _send_sync_state(self, state_vector):
        state_update, server_state_vector = await self._load_sync_state(state_vector)
        await self.send(bytes_data=_sync_message(1, state_update))
        await self.send(bytes_data=_sync_message(0, server_state_vector))

    @database_sync_to_async
    def _document_access(self, document_id, user):
        if not user.is_authenticated:
            return None
        try:
            document = FileEntry.objects.select_related("workspace").get(
                id=document_id, kind=FileEntry.Kind.FILE
            )
        except (ValueError, FileEntry.DoesNotExist):
            return None
        workspace = document.workspace
        if workspace.owner_id == user.id:
            role = "owner"
        else:
            role = WorkspaceMembership.objects.filter(
                workspace=workspace, user=user
            ).values_list("role", flat=True).first()
        if role is None:
            return None
        return str(document.id), role

    @database_sync_to_async
    def _persist_update(self, update):
        digest = hashlib.sha256(update).hexdigest()
        try:
            with transaction.atomic():
                FileEntry.objects.select_for_update().get(id=self.document_id)
                _, created = DocumentUpdate.objects.get_or_create(
                    document_id=self.document_id,
                    update_hash=digest,
                    defaults={"update": update, "author_id": self.scope["user"].id},
                )
                if not created:
                    return False

                FileEntry.objects.filter(
                    id=self.document_id, yjs_initializing_until__isnull=False
                ).update(yjs_initializing_until=None)
                snapshot = DocumentSnapshot.objects.filter(
                    document_id=self.document_id
                ).first()
                compacted_through_id = (
                    snapshot.compacted_through_id if snapshot is not None else 0
                )
                pending = DocumentUpdate.objects.filter(
                    document_id=self.document_id, id__gt=compacted_through_id
                )
                if pending.count() >= UPDATE_COMPACTION_THRESHOLD:
                    self._compact_updates(snapshot, pending)
                return True
        except IntegrityError:
            return False

    def _compact_updates(self, snapshot, pending):
        document = YDoc()
        compacted_through_id = 0
        if snapshot is not None:
            _apply_yjs_update(document, bytes(snapshot.state))
            compacted_through_id = snapshot.compacted_through_id

        updates = list(pending.order_by("id").values_list("id", "update"))
        for update_id, update in updates:
            _apply_yjs_update(document, bytes(update))
            compacted_through_id = update_id

        DocumentSnapshot.objects.update_or_create(
            document_id=self.document_id,
            defaults={
                "state": encode_state_as_update(document),
                "state_vector": encode_state_vector(document),
                "compacted_through_id": compacted_through_id,
            },
        )
        retained_ids = DocumentUpdate.objects.filter(
            document_id=self.document_id
        ).order_by("-id").values("id")[:UPDATE_RETENTION_LIMIT]
        DocumentUpdate.objects.filter(
            document_id=self.document_id, id__lte=compacted_through_id
        ).exclude(id__in=retained_ids).delete()

    @database_sync_to_async
    def _load_sync_state(self, state_vector):
        snapshot = DocumentSnapshot.objects.filter(document_id=self.document_id).first()
        document = YDoc()
        compacted_through_id = 0
        if snapshot is not None:
            _apply_yjs_update(document, bytes(snapshot.state))
            compacted_through_id = snapshot.compacted_through_id
        updates = DocumentUpdate.objects.filter(
            document_id=self.document_id, id__gt=compacted_through_id
        ).order_by("id").values_list("update", flat=True)
        for update in updates:
            _apply_yjs_update(document, bytes(update))
        return (
            _encode_yjs_state(document, state_vector, "Invalid Yjs state vector"),
            encode_state_vector(document),
        )
