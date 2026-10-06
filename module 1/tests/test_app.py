import io
import unittest

import pandas as pd

import app as cleaning_app


class DataCleaningTests(unittest.TestCase):
    def setUp(self):
        cleaning_app.app.config["TESTING"] = True
        cleaning_app.DATASETS.clear()
        self.client = cleaning_app.app.test_client()

    def test_sample_detects_common_problems(self):
        response = self.client.post("/api/sample")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreater(payload["analysis"]["missingTotal"], 0)
        self.assertGreater(payload["analysis"]["duplicateRows"], 0)
        self.assertGreater(payload["analysis"]["duplicateIds"], 0)
        self.assertGreater(payload["analysis"]["invalidNumeric"], 0)
        self.assertGreater(payload["analysis"]["invalidDates"], 0)

    def test_cleaning_preserves_source_and_exports_clean_copy(self):
        loaded = self.client.post("/api/sample").get_json()
        token = loaded["token"]
        original_before = cleaning_app.DATASETS[token]["original"].copy(deep=True)
        response = self.client.post("/api/clean", json={
            "token": token,
            "options": {"removeEmptyRows": True, "removeDuplicates": True, "trimSpaces": True, "convertTypes": True, "handleInvalid": True},
            "missingStrategy": "custom",
            "customValue": "Unknown",
            "requiredFields": ["Full Name"],
            "idColumn": "Customer ID",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(cleaning_app.DATASETS[token]["original"].equals(original_before))
        self.assertLess(response.get_json()["stats"]["cleanedRows"], len(original_before))
        self.assertGreater(response.get_json()["stats"]["formattingCorrections"], 0)
        download = self.client.get(f"/api/download/{token}")
        self.assertEqual(download.status_code, 200)
        self.assertIn("cleaned_", download.headers["Content-Disposition"])
        self.assertIn(b"Customer ID", download.data)

    def test_upload_rejects_non_csv(self):
        response = self.client.post("/api/upload", data={"file": (io.BytesIO(b"hello"), "notes.txt")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)

    def test_duplicate_source_headers_are_reported(self):
        response = self.client.post("/api/upload", data={"file": (io.BytesIO(b"id,id\n1,2\n"), "duplicate_headers.csv")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        checks = response.get_json()["analysis"]["validations"]
        column_check = next(item for item in checks if item["label"] == "Column names")
        self.assertEqual(column_check["status"], "invalid")
        self.assertIn("duplicate", column_check["detail"].casefold())

    def test_validation_rules_are_applied(self):
        frame = pd.DataFrame({"id": ["1", "1"], "amount": ["4", "12"]})
        analysis = cleaning_app.analyze_frame(frame, {"requiredFields": ["id", "amount"], "idColumn": "id", "rangeColumn": "amount", "rangeMin": 5, "rangeMax": 10})
        statuses = {item["label"]: item["status"] for item in analysis["validations"]}
        self.assertEqual(statuses["Unique ID"], "invalid")
        self.assertEqual(statuses["Numerical range"], "invalid")


if __name__ == "__main__":
    unittest.main()
