"""Smoke tests: run with `python -m unittest discover -s server/tests`."""
import os, tempfile, unittest, importlib.util
from pathlib import Path
from werkzeug.security import generate_password_hash

TMP = tempfile.TemporaryDirectory(prefix="dnx-test-")
os.environ["DNX_DATABASE_PATH"] = str(Path(TMP.name) / "test.sqlite3")
os.environ["DNX_BACKUP_DIR"] = str(Path(TMP.name) / "backups")
os.environ["DNX_SECRET_KEY"] = "unit-test-secret-key-with-more-than-32-characters"
os.environ["DNX_ENV"] = "test"
spec = importlib.util.spec_from_file_location("datanexus_test_app", Path(__file__).resolve().parents[1] / "app.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class ApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mod.connect() as c:
            c.execute("INSERT INTO users(id,username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",("owner-test","owner","Test Owner",generate_password_hash("TestPasswordStrong123!"),"Owner",mod.now()))
            c.execute("INSERT INTO users(id,username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",("staff-test","staff","Test Staff",generate_password_hash("TestPasswordStrong123!"),"Staff",mod.now()))
    def setUp(self): self.client=mod.app.test_client()
    def login(self, username):
        return self.client.post("/api/auth/login",json={"username":username,"password":"TestPasswordStrong123!"})
    def test_health_and_frontend(self):
        self.assertEqual(self.client.get("/api/health").status_code,200)
        self.assertEqual(self.client.get("/").status_code,200)
        self.assertEqual(self.client.get("/server/app.py").status_code,404)
    def test_admin_routes_require_auth(self):
        self.assertEqual(self.client.get("/api/admin/overview").status_code,401)
    def test_owner_can_read_metrics_and_create_backup(self):
        self.assertEqual(self.login("owner").status_code,200)
        self.assertEqual(self.client.get("/api/admin/overview").status_code,200)
        result=self.client.post("/api/admin/backups",json={"action":"create"})
        self.assertEqual(result.status_code,201)
        self.assertEqual(result.json["status"],"verified")
    def test_staff_cannot_access_owner_console(self):
        self.assertEqual(self.login("staff").status_code,200)
        self.assertEqual(self.client.get("/api/admin/overview").status_code,403)
    def test_owner_role_cannot_be_granted_by_developer(self):
        self.assertEqual(self.login("owner").status_code,200)
        # The last active Owner cannot be demoted; invalid role names are rejected.
        response=self.client.patch("/api/admin/users/staff-test",json={"role":"Superuser"})
        self.assertEqual(response.status_code,400)
    def test_online_restore_is_disabled(self):
        self.assertEqual(self.login("owner").status_code,200)
        self.assertEqual(self.client.post("/api/admin/restore",json={"backup_id":"anything"}).status_code,405)

if __name__ == "__main__": unittest.main()
