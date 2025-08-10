from datetime import datetime, timezone
import requests
import os
import time
import getpass
import json
from datetime import datetime

# --- Configuration ---
BSKY_HOST = "https://bsky.social"

def clean_input(input_string):
    """
    A robust function to remove all non-printable characters from a string,
    which can be accidentally copied from web pages or terminals.
    """
    return ''.join(filter(str.isprintable, input_string))

class BlueskySession:
    """
    Manages a session with the Bluesky API, including automatic token refresh.
    """
    def __init__(self, handle, password):
        self._handle = handle
        self._password = password
        self.access_jwt = None
        self.refresh_jwt = None
        self.did = None
        self.session_active = False

    def create_session(self):
        """
        Creates an initial session with the Bluesky server.
        """
        print("Attempting to create a session...")
        try:
            response = requests.post(
                f"{BSKY_HOST}/xrpc/com.atproto.server.createSession",
                json={"identifier": self._handle, "password": self._password},
            )
            response.raise_for_status()
            data = response.json()
            self.access_jwt = data['accessJwt']
            self.refresh_jwt = data['refreshJwt']
            self.did = data['did']
            self.session_active = True
            print(f"✅ Session created successfully for handle: {data['handle']}")
            return True
        except requests.exceptions.HTTPError as e:
            print(f"❌ Failed to create session. Status Code: {e.response.status_code}")
            print(f"   Error: {e.response.json().get('message', 'No error message provided.')}")
            return False

    def _refresh_session(self):
        """
        Uses the refresh token to get a new access token.
        """
        print("\n⚠️ Access token expired. Refreshing session...")
        if not self.refresh_jwt:
            print("❌ No refresh token available. Cannot refresh session.")
            self.session_active = False
            return False
        
        try:
            response = requests.post(
                f"{BSKY_HOST}/xrpc/com.atproto.server.refreshSession",
                headers={"Authorization": f"Bearer {self.refresh_jwt}"},
            )
            response.raise_for_status()
            data = response.json()
            self.access_jwt = data['accessJwt']
            self.refresh_jwt = data['refreshJwt']
            print("✅ Session refreshed successfully.")
            return True
        except requests.exceptions.HTTPError as e:
            print(f"❌ Failed to refresh session. Status Code: {e.response.status_code}")
            self.session_active = False
            return False

    def _make_request(self, method, xrpc_endpoint, params=None, json_data=None, headers=None, is_retry=False):
        """
        A generic, authenticated request handler that includes automatic token refresh logic.
        """
        if not self.session_active:
            raise Exception("Session is not active. Please create a session first.")

        if headers is None: headers = {}
        headers["Authorization"] = f"Bearer {self.access_jwt}"
        full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
        
        try:
            response = requests.request(method, full_url, params=params, json=json_data, headers=headers)
            response.raise_for_status()
            if response.content:
                return response.json()
            return None
        except requests.exceptions.HTTPError as e:
            error_data = e.response.json()
            if e.response.status_code == 400 and error_data.get('error') == 'ExpiredToken' and not is_retry:
                if self._refresh_session():
                    return self._make_request(method, xrpc_endpoint, params=params, json_data=json_data, headers=headers, is_retry=True)
                else:
                    raise e
            else:
                print(f"❌ An API error occurred: {error_data.get('message')}")
                raise e


    def get_all_user_posts(self, actor_handle, start_time=None, end_time=None, max_posts=None):
        """
        Fetches posts for a given user using pagination, with optional timestamp filtering and limit.
        """
        print(f"\nFetching posts for @{actor_handle}...")
        all_posts = []
        cursor = None
        
        # If no filter, use full range
        if start_time is None:
            start_time = datetime.min.replace(tzinfo=timezone.utc)
        if end_time is None:
            end_time = datetime.max.replace(tzinfo=timezone.utc)
        
        while True:
            params = {
                "actor": actor_handle,
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor

            try:
                response = self._make_request("GET", "app.bsky.feed.getAuthorFeed", params=params)
                posts_on_page = response.get('feed', [])
                if not posts_on_page:
                    print("No more posts found for this user.")
                    break

                for post in posts_on_page:
                    try:
                        post_time = datetime.fromisoformat(post['post']['record']['createdAt'].replace("Z", "+00:00"))
                    except Exception:
                        continue  # Skip malformed dates
                    
                    if start_time <= post_time <= end_time:
                        all_posts.append(post)
                        if max_posts and len(all_posts) >= max_posts:
                            print("Reached requested number of posts.")
                            return all_posts
                    elif post_time < start_time:
                        # We are past the desired range, no need to fetch further
                        print("Reached posts older than start time. Stopping.")
                        return all_posts

                print(f"   Fetched {len(all_posts)} posts so far within time range.")
                cursor = response.get('cursor')
                if not cursor:
                    print("Reached the end of the feed.")
                    break
                
                time.sleep(1)

            except Exception as e:
                print(f"Error while fetching: {e}")
                break
        
        return all_posts


def search_and_select_user(session):
    """
    Prompts the user for a keyword, searches for users, and lets them select one.
    """
    query = clean_input(input("Enter a keyword to search for users (e.g., space): "))
    if not query:
        print("Search canceled.")
        return None
    
    try:
        print(f"Searching for users matching '{query}'...")
        response = session._make_request("GET", "app.bsky.actor.searchActors", params={"q": query, "limit": 25})
        actors = response.get('actors', [])
        
        if not actors:
            print("No users found with that keyword.")
            return None
            
        print("\n--- Found Users ---")
        for i, actor in enumerate(actors):
            display_name = f"({actor.get('displayName')})" if actor.get('displayName') else ""
            print(f"[{i+1}] @{actor.get('handle')} {display_name}")
        print("[0] Cancel Search")
        
        while True:
            try:
                choice = int(input("Enter the number of the user you want to select: "))
                if 0 <= choice <= len(actors):
                    if choice == 0:
                        print("Search canceled.")
                        return None
                    return actors[choice - 1]['handle']
                else:
                    print("Invalid number. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number.")

    except Exception as e:
        print(f"An error occurred during search: {e}")
        return None

if __name__ == "__main__":
    print("--- Bluesky User Post Archiver ---")
    
    user_handle = clean_input(input("Enter your Bluesky handle (e.g., yourname.bsky.social): "))
    app_password = clean_input(input("Enter your App Password (will be visible): "))

    session = BlueskySession(user_handle, app_password)
    if session.create_session():
        
        target_handle = None
        while True:
            print("\nHow would you like to select a user to archive?")
            print("[1] Enter a user's handle directly")
            print("[2] Search for a user by keyword")
            choice = clean_input(input("Enter your choice (1 or 2): "))
            
            if choice == '1':
                target_handle = clean_input(input("Please enter the user handle to fetch (e.g., nasa.bsky.social): "))
                if target_handle:
                    break
            elif choice == '2':
                target_handle = search_and_select_user(session)
                if target_handle:
                    break
            else:
                print("Invalid choice. Please enter 1 or 2.")

        # ----------------- Timestamp filter prompt -----------------
        filter_choice = clean_input(input("\nDo you want to filter posts by timestamp? (y/n): ")).lower()
        start_time, end_time, max_posts = None, None, None

        if filter_choice == 'y':
            from datetime import timezone
            start_input = clean_input(input("Enter start timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
            end_input = clean_input(input("Enter end timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
            max_posts_input = clean_input(input("Enter max number of posts to fetch (blank for no limit): "))

            try:
                if start_input:
                    start_time = datetime.strptime(start_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if end_input:
                    end_time = datetime.strptime(end_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if max_posts_input:
                    max_posts = int(max_posts_input)
            except ValueError:
                print("⚠️ Invalid date format. Please use YYYY-MM-DD HH:MM:SS")
                exit(1)
        # ------------------------------------------------------------

        if target_handle:
            user_posts = session.get_all_user_posts(
                actor_handle=target_handle,
                start_time=start_time,
                end_time=end_time,
                max_posts=max_posts
            )
            
            print(f"\n✨ --- Fetching Complete --- ✨")
            print(f"Total posts retrieved for @{target_handle}: {len(user_posts)}")

            if user_posts:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                safe_handle = target_handle.replace('.', '_')
                filename = f"posts_{safe_handle}_{timestamp}.json"
                
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(user_posts, f, ensure_ascii=False, indent=4)
                    print(f"\n✅ Successfully saved {len(user_posts)} posts to '{filename}'")
                except Exception as e:
                    print(f"\n❌ Failed to save posts to file. Error: {e}")
