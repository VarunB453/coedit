import asyncio
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from editor.models import DocumentUpdate, FileEntry, Workspace, WorkspaceMembership
from editor.socket.consumers import MAX_WEBSOCKET_MESSAGE_BYTES, EditorConsumer
from editor.socket.routing import websocket_urlpatterns


class WorkspaceFileApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="long-test-password")
        self.workspace = Workspace.objects.create(name="Project", owner=self.owner)
        self.workspace_id = self.workspace.id
        self.files_url = f"/api/workspaces/{self.workspace_id}/files/"
        self.client.force_login(self.owner)

    def create_entry(self, name, kind="file", parent_id=None):
        return self.client.post(
            self.files_url,
            data={"name": name, "kind": kind, "parent_id": parent_id},
            content_type="application/json",
        )

    def test_registration_login_and_logout_use_authenticated_sessions(self):
        client = Client(enforce_csrf_checks=True)
        csrf = client.get("/api/csrf/").json()["csrfToken"]
        credentials = {"username": "new-member", "password": "C0llab!Long-passphrase-9"}
        registered = client.post(
            "/api/auth/register/",
            data=credentials,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(client.get("/api/auth/session/").json()["username"], "new-member")

        csrf = client.get("/api/csrf/").json()["csrfToken"]
        logged_out = client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(client.get("/api/auth/session/").status_code, 401)

        csrf = client.get("/api/csrf/").json()["csrfToken"]
        logged_in = client.post(
            "/api/auth/session/",
            data=credentials,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(client.get("/api/auth/session/").json()["username"], "new-member")

    def test_create_list_and_reject_duplicate_sibling_names(self):
        created = self.create_entry("notes.txt")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], "notes.txt")
        detail = self.client.get(f"{self.files_url}{created.json()['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], created.json()["id"])

        duplicate = self.create_entry("NOTES.txt")
        self.assertEqual(duplicate.status_code, 409)
        listing = self.client.get(self.files_url).json()
        self.assertEqual(listing["role"], "owner")
        self.assertEqual(len(listing["entries"]), 1)

    def test_folder_delete_removes_descendants(self):
        folder = self.create_entry("docs", kind="folder").json()
        child = self.create_entry("readme.md", parent_id=folder["id"])
        self.assertEqual(child.status_code, 201)

        deleted = self.client.delete(f"{self.files_url}{folder['id']}/")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get(self.files_url).json()["entries"], [])

    def test_folder_cannot_move_into_its_descendant(self):
        parent = self.create_entry("parent", kind="folder").json()
        child = self.create_entry("child", kind="folder", parent_id=parent["id"]).json()

        response = self.client.patch(
            f"{self.files_url}{parent['id']}/",
            data={"parent_id": child["id"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_nonportable_file_names(self):
        for name in ("../secret", "CON.txt", "bad:name", "trailing.", "x" * 101):
            with self.subTest(name=name):
                response = self.create_entry(name)
                self.assertEqual(response.status_code, 400)

    def test_anonymous_and_nonmember_access_is_denied(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.files_url).status_code, 401)
        stranger = get_user_model().objects.create_user(username="stranger", password="password")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.files_url).status_code, 404)

    def test_viewer_can_read_but_cannot_change_documents(self):
        viewer = get_user_model().objects.create_user(username="viewer", password="password")
        WorkspaceMembership.objects.create(
            workspace=self.workspace, user=viewer, role=WorkspaceMembership.Role.VIEWER
        )
        entry = self.create_entry("notes.txt").json()
        self.client.force_login(viewer)

        self.assertEqual(self.client.get(self.files_url).status_code, 200)
        self.assertEqual(self.client.get(f"{self.files_url}{entry['id']}/").status_code, 200)
        create = self.create_entry("other.txt")
        update = self.client.patch(
            f"{self.files_url}{entry['id']}/",
            data={"name": "changed.txt"},
            content_type="application/json",
        )
        delete = self.client.delete(f"{self.files_url}{entry['id']}/")
        self.assertEqual(create.status_code, 403)
        self.assertEqual(update.status_code, 403)
        self.assertEqual(delete.status_code, 403)

    def test_only_owner_can_grant_workspace_roles(self):
        editor = get_user_model().objects.create_user(username="editor", password="password")
        members_url = f"/api/workspaces/{self.workspace_id}/members/"
        response = self.client.post(
            members_url,
            data={"username": "editor", "role": "editor"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["role"], "editor")
        self.assertTrue(WorkspaceMembership.objects.filter(workspace=self.workspace, user=editor).exists())

        viewer = get_user_model().objects.create_user(username="viewer", password="password")
        WorkspaceMembership.objects.create(
            workspace=self.workspace, user=viewer, role=WorkspaceMembership.Role.VIEWER
        )
        self.client.force_login(editor)
        denied = self.client.post(
            members_url,
            data={"username": "viewer", "role": "editor"},
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_legacy_workspace_is_not_implicitly_claimed(self):
        legacy = Workspace.objects.create()
        response = self.client.get(f"/api/workspaces/{legacy.id}/files/")
        self.assertEqual(response.status_code, 404)
        legacy.refresh_from_db()
        self.assertIsNone(legacy.owner_id)

    def test_api_mutations_require_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        url = f"/api/workspaces/{self.workspace_id}/files/"
        payload = {"name": "csrf.txt", "kind": "file"}

        rejected = client.post(url, data=payload, content_type="application/json")
        self.assertEqual(rejected.status_code, 403)

        token = client.get("/api/csrf/").json()["csrfToken"]
        accepted = client.post(
            url,
            data=payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(accepted.status_code, 201)

    def test_initialization_lease_allows_only_one_editor_to_seed_document(self):
        content = {
            "type": "doc",
            "content": [{"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Legacy"}]}],
        }
        document = FileEntry.objects.create(
            workspace=self.workspace,
            name="legacy.md",
            kind=FileEntry.Kind.FILE,
            content=content,
        )
        url = f"/api/workspaces/{self.workspace_id}/files/{document.id}/initialize/"

        first = self.client.post(url)
        second = self.client.post(url)
        self.assertEqual(first.json(), {"ready": True, "initialize": True})
        self.assertFalse(second.json()["ready"])

        document.yjs_initializing_until = timezone.now() - timedelta(seconds=1)
        document.save(update_fields=["yjs_initializing_until"])
        retry = self.client.post(url)
        self.assertEqual(retry.json(), {"ready": True, "initialize": True})


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class DurableCollaborationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="long-test-password")
        self.viewer = User.objects.create_user(username="viewer", password="long-test-password")
        self.workspace = Workspace.objects.create(owner=self.owner, name="Sync")
        self.document = FileEntry.objects.create(
            workspace=self.workspace, name="one.txt", kind=FileEntry.Kind.FILE
        )
        self.other_document = FileEntry.objects.create(
            workspace=self.workspace, name="two.txt", kind=FileEntry.Kind.FILE
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace, user=self.viewer, role=WorkspaceMembership.Role.VIEWER
        )

    def consumer(self, user, document_id=None):
        consumer = EditorConsumer({"user": user})
        consumer.scope = {"user": user}
        consumer.document_id = str(document_id or self.document.id)
        return consumer

    def test_duplicate_updates_are_deduplicated_and_recoverable_after_consumer_restart(self):
        update = b"durable-yjs-update"
        concurrent_update = b"second-concurrent-update"

        async def persist_concurrently():
            consumers = [self.consumer(self.owner) for _ in range(3)]
            return await asyncio.gather(
                consumers[0]._persist_update(update),
                consumers[1]._persist_update(update),
                consumers[2]._persist_update(concurrent_update),
            )

        results = async_to_sync(persist_concurrently)()
        self.assertEqual(sum(results), 2)
        self.assertEqual(DocumentUpdate.objects.filter(document=self.document).count(), 2)

        connection.close()
        recovered = async_to_sync(self.consumer(self.owner)._load_updates)()
        self.assertEqual({bytes(value) for value in recovered}, {update, concurrent_update})

    def authenticated_app(self, user):
        inner = URLRouter(websocket_urlpatterns)

        async def app(scope, receive, send):
            scope = dict(scope)
            scope["user"] = user
            await inner(scope, receive, send)

        return app

    def test_rooms_are_isolated_and_viewer_updates_are_not_persisted(self):
        async def exercise_rooms():
            owner_app = self.authenticated_app(self.owner)
            first = WebsocketCommunicator(owner_app, f"/ws/editor/{self.document.id}")
            second = WebsocketCommunicator(owner_app, f"/ws/editor/{self.document.id}")
            isolated = WebsocketCommunicator(
                owner_app, f"/ws/editor/{self.other_document.id}"
            )
            connected = [await communicator.connect() for communicator in (first, second, isolated)]
            self.assertTrue(all(result[0] for result in connected))

            frame = b"\x00\x02\x01x"
            await first.send_to(bytes_data=frame)
            received = await second.receive_from(timeout=1)
            self.assertEqual(received, frame)
            self.assertTrue(await isolated.receive_nothing(timeout=0.1))

            viewer = WebsocketCommunicator(
                self.authenticated_app(self.viewer), f"/ws/editor/{self.document.id}"
            )
            viewer_connected, _ = await viewer.connect()
            self.assertTrue(viewer_connected)
            await viewer.send_to(bytes_data=b"\x00\x02\x01v")
            await asyncio.sleep(0)

            for communicator in (first, second, isolated, viewer):
                await communicator.disconnect()

            reconnected = WebsocketCommunicator(
                owner_app, f"/ws/editor/{self.document.id}"
            )
            connected, _ = await reconnected.connect()
            self.assertTrue(connected)
            await reconnected.send_to(bytes_data=b"\x00\x00\x01\x00")
            self.assertEqual(await reconnected.receive_from(timeout=1), frame)
            await reconnected.disconnect()

        async_to_sync(exercise_rooms)()
        self.assertEqual(DocumentUpdate.objects.filter(document=self.document).count(), 1)
        self.assertEqual(DocumentUpdate.objects.filter(document=self.other_document).count(), 0)

    def test_websocket_rejects_nonmembers_and_untrusted_origins(self):
        stranger = get_user_model().objects.create_user(username="stranger", password="password")

        async def exercise_denials():
            denied = WebsocketCommunicator(
                self.authenticated_app(stranger), f"/ws/editor/{self.document.id}"
            )
            connected, close_code = await denied.connect()
            self.assertFalse(connected)
            self.assertEqual(close_code, 4403)

            from core.asgi import application

            bad_origin = WebsocketCommunicator(
                application,
                f"/ws/editor/{self.document.id}",
                headers=[(b"origin", b"https://untrusted.example")],
            )
            connected, _ = await bad_origin.connect()
            self.assertFalse(connected)

        async_to_sync(exercise_denials)()

    def test_existing_editor_connections_respect_role_changes(self):
        editor = get_user_model().objects.create_user(username="editor", ******)
        membership = WorkspaceMembership.objects.create(
            workspace=self.workspace, user=editor, role=WorkspaceMembership.Role.EDITOR
        )

        async def exercise_role_change():
            communicator = WebsocketCommunicator(
                self.authenticated_app(editor), f"/ws/editor/{self.document.id}"
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            membership.role = WorkspaceMembership.Role.VIEWER
            membership.save(update_fields=["role"])
            await communicator.send_to(bytes_data=b"\x00\x02\x01v")
            self.assertTrue(await communicator.receive_nothing(timeout=0.1))
            self.assertEqual(
                DocumentUpdate.objects.filter(document=self.document).count(), 0
            )

            membership.delete()
            await communicator.send_to(bytes_data=b"\x00\x02\x01r")
            close_message = await communicator.receive_output(timeout=1)
            self.assertEqual(close_message["type"], "websocket.close")
            self.assertEqual(close_message["code"], 4403)
            await communicator.disconnect()

        async_to_sync(exercise_role_change)()

    def test_oversized_websocket_messages_are_closed(self):
        async def exercise_limit():
            communicator = WebsocketCommunicator(
                self.authenticated_app(self.owner), f"/ws/editor/{self.document.id}"
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.send_to(
                bytes_data=b"x" * (MAX_WEBSOCKET_MESSAGE_BYTES + 1)
            )
            close_message = await communicator.receive_output(timeout=1)
            self.assertEqual(close_message["type"], "websocket.close")
            self.assertEqual(close_message["code"], 4400)
            await communicator.disconnect()

        async_to_sync(exercise_limit)()
