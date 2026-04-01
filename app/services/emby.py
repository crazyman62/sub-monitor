import requests
from datetime import datetime
import dateutil.parser

class EmbyClient:
    def __init__(self, server_url, api_key):
        self.server_url = server_url.rstrip('/') if server_url else None
        self.api_key = api_key
        self.headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json'
        }

    def is_configured(self):
        return bool(self.server_url and self.api_key)

    def _get(self, endpoint):
        if not self.is_configured():
            return None
        url = f"{self.server_url}{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Emby API GET Error ({endpoint}): {e}")
            return None

    def _post(self, endpoint, data=None):
        if not self.is_configured():
            return None
        url = f"{self.server_url}{endpoint}"
        try:
            response = requests.post(url, headers=self.headers, json=data, timeout=10)
            response.raise_for_status()
            # Some post endpoints return empty content on success
            if response.content:
                return response.json()
            return True
        except requests.RequestException as e:
            print(f"Emby API POST Error ({endpoint}): {e}")
            return None

    def _delete(self, endpoint):
        if not self.is_configured():
            return None
        url = f"{self.server_url}{endpoint}"
        try:
            response = requests.delete(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Emby API DELETE Error ({endpoint}): {e}")
            return None

    def get_users(self):
        """Fetch all users from Emby."""
        return self._get('/emby/Users')

    def get_user(self, user_id):
        """Fetch a specific user."""
        return self._get(f'/emby/Users/{user_id}')

    def get_user_activity(self, user_id):
        """Fetch user activity (last login, device, ip)."""
        # In Emby, active sessions might contain current IP/Device
        # We can also check /emby/System/ActivityLog for more history if needed.
        # Alternatively, the user object itself has LastActivityDate and LastLoginDate
        # To get the last device/IP reliably without parsing huge activity logs,
        # we check current sessions for the user or fallback to basic user info.

        user_info = self.get_user(user_id)
        if not user_info:
            return None

        last_login_date = user_info.get('LastLoginDate')

        # Try to find recent sessions to get IP/Device
        sessions = self._get('/emby/Sessions')
        last_ip = None
        last_device = None

        if sessions:
            # Filter sessions for this user, sort by LastActivityDate desc
            user_sessions = [s for s in sessions if s.get('UserId') == user_id]
            if user_sessions:
                # Assuming the first one or latest one has the info
                latest_session = user_sessions[0] # Often already sorted
                last_ip = latest_session.get('RemoteEndPoint')
                last_device = latest_session.get('Client')
                if latest_session.get('DeviceName'):
                    last_device = f"{last_device} ({latest_session.get('DeviceName')})"

        # Fetch playback history
        # Emby's /Users/{UserId}/Items with Filters=IsPlayed or similar might work,
        # but let's query the sessions endpoint directly for active viewing, and
        # possibly we can't get past viewing without an activity log or playback plugin.
        # We will retrieve current active sessions.
        current_playing = []
        if sessions:
            user_sessions = [s for s in sessions if s.get('UserId') == user_id]
            for s in user_sessions:
                if s.get('NowPlayingItem'):
                    item = s.get('NowPlayingItem')
                    name = item.get('Name')
                    if item.get('Type') == 'Episode':
                        name = f"{item.get('SeriesName')} - {name}"
                    duration_ticks = s.get('PlayState', {}).get('PositionTicks', 0)
                    current_playing.append({
                        'device': s.get('Client'),
                        'ip': s.get('RemoteEndPoint'),
                        'show': name,
                        'duration': duration_ticks  # Note: Ticks are 10,000 per ms
                    })

        return {
            'last_login_date': last_login_date,
            'last_ip': last_ip,
            'last_device': last_device,
            'current_playing': current_playing
        }

    def disable_user(self, user_id):
        """Disable a user by setting their policy."""
        user = self.get_user(user_id)
        if not user or 'Policy' not in user:
            return False

        policy = user['Policy']
        policy['IsDisabled'] = True

        # Update user policy
        response = self._post(f'/emby/Users/{user_id}/Policy', data=policy)
        return response is not None

    def enable_user(self, user_id):
        """Enable a user."""
        user = self.get_user(user_id)
        if not user or 'Policy' not in user:
            return False

        policy = user['Policy']
        policy['IsDisabled'] = False

        response = self._post(f'/emby/Users/{user_id}/Policy', data=policy)
        return response is not None

    def disable_iptv(self, user_id):
        """Disable IPTV access for a user."""
        user = self.get_user(user_id)
        if not user or 'Policy' not in user:
            return False

        policy = user['Policy']
        policy['EnableLiveTvAccess'] = False

        response = self._post(f'/emby/Users/{user_id}/Policy', data=policy)
        return response is not None

    def enable_iptv(self, user_id):
        """Enable IPTV access for a user."""
        user = self.get_user(user_id)
        if not user or 'Policy' not in user:
            return False

        policy = user['Policy']
        policy['EnableLiveTvAccess'] = True

        response = self._post(f'/emby/Users/{user_id}/Policy', data=policy)
        return response is not None

    def get_past_activity(self, user_id):
        """Fetch past activity (like items played)."""
        try:
            # Querying the user's played items directly
            endpoint = f'/emby/Users/{user_id}/Items?IsPlayed=true&SortBy=DatePlayed&SortOrder=Descending&Recursive=true&IncludeItemTypes=Movie,Episode&Limit=20&Fields=Name,DatePlayed,Overview'
            items_response = self._get(endpoint)
            history = []
            if items_response and 'Items' in items_response:
                for item in items_response['Items']:
                    user_data = item.get('UserData', {})
                    played_date = user_data.get('LastPlayedDate')

                    name = item.get('Name')
                    if item.get('Type') == 'Episode' and item.get('SeriesName'):
                        name = f"{item.get('SeriesName')} - {name}"

                    history.append({
                        'name': name,
                        'date': played_date if played_date else 'Unknown',
                        'overview': item.get('Overview', '')
                    })
            return history
        except Exception:
            return []

    def delete_user(self, user_id):
        """Delete a user from Emby."""
        return self._delete(f'/emby/Users/{user_id}')
