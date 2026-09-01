import datetime as dt
import importlib.util
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "zoho_monthly_tickets.py"
spec = importlib.util.spec_from_file_location("zoho_monthly_tickets", MODULE_PATH)
zoho = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(zoho)


class ZohoMonthlyTicketsTests(unittest.TestCase):
    def test_template_rendering_uses_previous_month(self):
        ticket = {
            "ticket_key": "example",
            "run_day_of_month": 3,
            "subject_template": "Data for {last_month_name} {last_month_year}",
            "departmentId": "department",
            "contactId": "contact",
            "description_template": "Due {tat_date}",
            "tat_day_of_current_month": 4,
        }

        rendered = zoho.render_ticket(ticket, dt.date(2026, 8, 3))

        self.assertEqual(rendered["subject"], "Data for July 2026")
        self.assertEqual(rendered["description"], "Due 2026-08-04")
        self.assertNotIn("ticket_key", rendered)
        self.assertNotIn("run_day_of_month", rendered)

    def test_due_ticket_selection_catches_up(self):
        config = {
            "tickets": [
                {
                    "run_day_of_month": 1,
                    "subject": "Day one",
                    "departmentId": "department",
                    "contactId": "contact"
                },
                {
                    "run_day_of_month": 3,
                    "subject": "Day three",
                    "departmentId": "department",
                    "contactId": "contact"
                },
                {
                    "run_day_of_month": 7,
                    "subject": "Day seven",
                    "departmentId": "department",
                    "contactId": "contact"
                }
            ]
        }

        tickets = zoho.normalize_tickets(config, dt.date(2026, 8, 3))

        self.assertEqual([ticket["subject"] for ticket in tickets], ["Day one", "Day three"])

    def test_state_prevents_duplicate_ticket(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = pathlib.Path(tmp) / "state.json"
            key = "2026-08:abc123"
            zoho.save_ticket_completed(
                state_path,
                key,
                {"id": "1", "ticketNumber": "1001", "subject": "Example"}
            )

            self.assertTrue(
                zoho.completed_for_ticket(state_path, key, "Example", dt.date(2026, 8, 1))
            )


if __name__ == "__main__":
    unittest.main()

