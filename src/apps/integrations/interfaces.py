from typing import Protocol


class HrisClient(Protocol):
    def fetch_org_units(self) -> list[dict]:
        """[{code, name, kind, parent_code}]"""

    def fetch_employees(self) -> list[dict]:
        """[{employee_code, username, email, full_name, org_unit_code, title, entra_oid, active}]"""
