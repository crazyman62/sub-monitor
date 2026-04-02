import requests
import base64
from datetime import datetime, timedelta

class PayPalClient:
    def __init__(self, client_id, secret, sandbox=True):
        self.client_id = client_id
        self.secret = secret
        self.sandbox = sandbox
        self.base_url = "https://api-m.sandbox.paypal.com" if sandbox else "https://api-m.paypal.com"
        self.access_token = None
        self.token_expiry = None

    def _get_access_token(self):
        if self.access_token and self.token_expiry and datetime.utcnow() < self.token_expiry:
            return self.access_token

        url = f"{self.base_url}/v1/oauth2/token"
        auth_string = f"{self.client_id}:{self.secret}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"grant_type": "client_credentials"}

        try:
            response = requests.post(url, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            result = response.json()
            self.access_token = result.get('access_token')
            expires_in = result.get('expires_in', 3600)
            self.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in - 60) # 1 min buffer
            return self.access_token
        except requests.RequestException as e:
            print(f"Failed to get PayPal Access Token: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(e.response.text)
            return None

    def search_transactions(self, start_date, end_date):
        """
        Search for recent inbound, completed payments within a date range.
        start_date and end_date should be datetime objects.
        """
        token = self._get_access_token()
        if not token:
            return []

        # PayPal requires ISO-8601 format like: 2023-10-01T00:00:00-0700 or Z
        start_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        url = f"{self.base_url}/v1/reporting/transactions"
        params = {
            "start_date": start_str,
            "end_date": end_str,
            "fields": "transaction_info,payer_info",
            "page_size": 100
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }


        # Determine the start URL for pagination
        next_url = url
        current_params = params.copy()

        result = []

        while next_url:
            try:
                response = requests.get(next_url, headers=headers, params=current_params if current_params else None, timeout=10)
                response.raise_for_status()
                data = response.json()

                transactions = data.get('transaction_details', [])

                for t in transactions:
                    info = t.get('transaction_info', {})
                    payer = t.get('payer_info', {})

                    # Only care about completed inbound payments
                    # S = Success/Completed
                    if info.get('transaction_status') == 'S':
                        amount_obj = info.get('transaction_amount', {})
                        try:
                            value = float(amount_obj.get('value', 0))
                        except ValueError:
                            value = 0.0

                        # Only grab positive amounts (payments TO us)
                        if value > 0:
                            result.append({
                                'transaction_id': info.get('transaction_id'),
                                'amount': value,
                                'currency': amount_obj.get('currency_code'),
                                'date': info.get('transaction_initiation_date'),
                                'payer_email': payer.get('email_address'),
                                'payer_name': payer.get('payer_name', {}).get('alternate_full_name', '')
                            })

                # Check pagination links
                links = data.get('links', [])
                next_url_obj = next((link for link in links if link.get('rel') == 'next'), None)
                if next_url_obj:
                    next_url = next_url_obj.get('href')
                    # Parameters are already embedded in the next URL usually
                    current_params = {}
                else:
                    next_url = None

            except requests.RequestException as e:
                print(f"PayPal Transaction Search Error: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(e.response.text)
                return result

        return result
