import tempfile
import unittest
from pathlib import Path

from automatizacion_notificaciones import create_weekly_pdf, summarize_weekly_data


class WeeklyReportTests(unittest.TestCase):
    def test_summary_counts_only_evaluable_tickets_for_sla(self):
        rows = [
            {"SLA_Cumplido": True, "FechaCierre": object(), "AlertaTension": "NORMAL"},
            {"SLA_Cumplido": False, "FechaCierre": object(), "AlertaTension": "ALERTA"},
            {"SLA_Cumplido": None, "FechaCierre": None, "AlertaTension": "NORMAL"},
            {"SLA_Cumplido": False, "FechaCierre": None, "AlertaTension": "ALERTA"},
        ]

        summary = summarize_weekly_data(rows)

        self.assertEqual(summary["tickets_total"], 4)
        self.assertEqual(summary["tickets_closed"], 2)
        self.assertEqual(summary["sla_evaluable"], 3)
        self.assertAlmostEqual(summary["sla_compliance_pct"], 100 / 3)
        self.assertEqual(summary["voltage_alerts"], 2)
        self.assertEqual(summary["overdue_open"], 1)

    def test_empty_week_still_produces_a_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weekly.pdf"

            summary = create_weekly_pdf([], path)

            self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
            self.assertEqual(summary["tickets_total"], 0)
            self.assertEqual(summary["sla_compliance_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
