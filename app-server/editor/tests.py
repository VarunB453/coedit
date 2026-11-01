import uuid

from django.test import TestCase


class WorkspaceFileApiTests(TestCase):
	def setUp(self):
		self.workspace_id = uuid.uuid4()
		self.files_url = f"/api/workspaces/{self.workspace_id}/files/"

	def create_entry(self, name, kind="file", parent_id=None):
		return self.client.post(
			self.files_url,
			data={"name": name, "kind": kind, "parent_id": parent_id},
			content_type="application/json",
		)

	def test_create_list_and_reject_duplicate_sibling_names(self):
		created = self.create_entry("notes.txt")
		self.assertEqual(created.status_code, 201)
		self.assertEqual(created.json()["name"], "notes.txt")

		duplicate = self.create_entry("NOTES.txt")
		self.assertEqual(duplicate.status_code, 409)
		self.assertEqual(len(self.client.get(self.files_url).json()), 1)

	def test_folder_delete_removes_descendants(self):
		folder = self.create_entry("docs", kind="folder").json()
		child = self.create_entry("readme.md", parent_id=folder["id"])
		self.assertEqual(child.status_code, 201)

		deleted = self.client.delete(f"{self.files_url}{folder['id']}/")
		self.assertEqual(deleted.status_code, 200)
		self.assertEqual(self.client.get(self.files_url).json(), [])

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
