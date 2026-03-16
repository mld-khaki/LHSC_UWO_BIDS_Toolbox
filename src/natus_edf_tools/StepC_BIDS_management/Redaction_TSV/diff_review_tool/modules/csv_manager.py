import csv

class CSVManager:

    def __init__(self, csv_path):
        self.csv_path = csv_path
        self.rows = []
        self.load()

    def load(self):
        with open(self.csv_path, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.rows = list(reader)
            self.fields = reader.fieldnames

        extra = [
            "review_status",
            "diffs_total",
            "accepted",
            "discarded",
            "output_path"
        ]

        for col in extra:
            if col not in self.fields:
                self.fields.append(col)

    def save(self):
        with open(self.csv_path, "w", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fields)
            writer.writeheader()
            writer.writerows(self.rows)

    def get_files(self):

        results = []

        for r in self.rows:

            if r.get("status","").lower() == "processed":

                if r.get("review_status","") not in ["completed"]:

                    results.append(r)

        return results