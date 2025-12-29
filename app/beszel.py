import time
import unicodedata
import re
import requests

def normalize_name(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("S"))  # strip emoji/symbols
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

class BeszelClient:
    def __init__(self, base_url: str, email: str, password: str, timeout=3.0):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.timeout = timeout
        self._token = None
        self._token_at = 0
        self._ttl = 60 * 10

    def _get_token(self) -> str:
        now = int(time.time())
        if self._token and (now - self._token_at) < self._ttl:
            return self._token

        url = f"{self.base_url}/api/collections/_superusers/auth-with-password"
        r = requests.post(url, json={"identity": self.email, "password": self.password},
                          timeout=self.timeout, headers={"Accept": "application/json"})
        r.raise_for_status()
        token = r.json().get("token")
        if not token:
            raise RuntimeError("No token from Beszel/PocketBase auth")
        self._token = token
        self._token_at = now
        return token

    def _headers(self):
        return {"Accept": "application/json", "Authorization": f"Bearer {self._get_token()}"}

    def list_records(self, collection: str, *, per_page=200, page=1, filter_str=None, sort=None):
        url = f"{self.base_url}/api/collections/{collection}/records"
        params = {"perPage": per_page, "page": page}
        if filter_str:
            params["filter"] = filter_str
        if sort:
            params["sort"] = sort
        r = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def first_record(self, collection: str, *, filter_str=None, sort=None):
        data = self.list_records(collection, per_page=1, page=1, filter_str=filter_str, sort=sort)
        items = data.get("items", [])
        return items[0] if items else None
