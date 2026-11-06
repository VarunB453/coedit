import hashlib

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction

from editor.models import DocumentUpdate, FileEntry, Workspace, WorkspaceMembership


MAX_WEBSOCKET_MESSAGE_BYTES = 1_000_000


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


def _write_var_uint(value):
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _update_message(update):
    return _write_var_uint(0) + _write_var_uint(2) + _write_var_uint(len(update)) + update


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
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, bytes_data=None, text_data=None):
        if bytes_data is None or len(bytes_data) > MAX_WEBSOCKET_MESSAGE_BYTES:
            await self.close(code=4400)
            return
        try:
            message_type, offset = _read_var_uint(bytes_data, 0)
            if message_type == 0:
                sync_type, offset = _read_var_uint(bytes_data, offset)
                if sync_type in (1, 2):
                    if not await self._refresh_access():
                        return
                    if self.role == WorkspaceMembership.Role.VIEWER:
                        return
                    update_length, update_offset = _read_var_uint(bytes_data, offset)
                    update = bytes_data[update_offset:update_offset + update_length]
                    if len(update) != update_length or update_offset + update_length != len(bytes_data):
                        raise ValueError("Incomplete Yjs update")
                    created = await self._persist_update(update)
                    if created:
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {"type": "editor_message", "bytes_data": _update_message(update)},
                        )
                    return
                if sync_type == 0:
                    updates = await self._load_updates()
                    for update in updates or [b"\x00\x00"]:
                        await self.send(bytes_data=_update_message(update))
                    return
                raise ValueError("Unsupported Yjs sync message")
            if message_type in (1, 3):
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {"type": "editor_message", "bytes_data": bytes_data},
                )
                return
            raise ValueError("Unsupported Yjs message")
        except (IndexError, ValueError):
            await self.close(code=4400)

    async def editor_message(self, event):
        await self.send(bytes_data=event["bytes_data"])

    async def _refresh_access(self):
        access = await self._document_access(
            self.document_id, self.scope.get("user", AnonymousUser())
        )
        if access is None:
            await self.close(code=4403)
            return False
        self.document_id, self.role = access
        return True

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
        if role == WorkspaceMembership.Role.VIEWER:
            return str(document.id), role
        return str(document.id), role

    @database_sync_to_async
    def _persist_update(self, update):
        digest = hashlib.sha256(update).hexdigest()
        try:
            with transaction.atomic():
                _, created = DocumentUpdate.objects.get_or_create(
                    document_id=self.document_id,
                    update_hash=digest,
                    defaults={"update": update, "author_id": self.scope["user"].id},
                )
                if created:
                    FileEntry.objects.filter(
                        id=self.document_id, yjs_initializing_until__isnull=False
                    ).update(yjs_initializing_until=None)
                return created
        except IntegrityError:
            return False

    @database_sync_to_async
    def _load_updates(self):
        return list(
            DocumentUpdate.objects.filter(document_id=self.document_id)
            .order_by("id")
            .values_list("update", flat=True)
        )
