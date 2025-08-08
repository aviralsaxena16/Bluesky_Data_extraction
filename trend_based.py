import requests
import os
import time
import getpass
import json
from datetime import datetime

# --- Configuration ---
# The unique URI for the "What's Hot Classic" feed generator.
# This is stable and can be used consistently.
WHATS_HOT_FEED_URI = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"
BSKY_HOST = "https://bsky.social"

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
        Must be called once before making other authenticated requests.
        """
        print("Attempting to create a session...")
        try:
            response = requests.post(
                f"{BSKY_HOST}/xrpc/com.atproto.server.createSession",
                json={
                    "identifier": self._handle,
                    "password": self._password,
                },
            )
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
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
        This method is called automatically when a token expires.
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
            self.refresh_jwt = data['refreshJwt'] # The server might issue a new refresh token
            print("✅ Session refreshed successfully.")
            return True
        except requests.exceptions.HTTPError as e:
            print(f"❌ Failed to refresh session. Status Code: {e.response.status_code}")
            print(f"   Error: {e.response.json().get('message', 'Refresh failed.')}")
            self.session_active = False
            return False

    def _make_request(self, method, xrpc_endpoint, params=None, headers=None, is_retry=False):
        """
        A generic, authenticated request handler that includes automatic token refresh logic.
        """
        if not self.session_active:
            raise Exception("Session is not active. Please create a session first.")

        if headers is None:
            headers = {}
        
        # Add the current access token to the request
        headers["Authorization"] = f"Bearer {self.access_jwt}"

        full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
        
        try:
            response = requests.request(method, full_url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            # Check if the error is due to an expired token
            error_data = e.response.json()
            if e.response.status_code == 400 and error_data.get('error') == 'ExpiredToken' and not is_retry:
                # Token expired, try to refresh and retry the request once.
                if self._refresh_session():
                    return self._make_request(method, xrpc_endpoint, params=params, headers=headers, is_retry=True)
                else:
                    # Refresh failed, re-raise the original exception
                    raise e
            else:
                # It was a different error, so just raise it
                print(f"❌ An API error occurred: {error_data.get('message')}")
                raise e

    def get_whats_hot_classic(self, max_posts):
        """
        Fetches a large number of posts from the 'What's Hot Classic' feed
        using pagination.
        """
        print(f"\nFetching up to {max_posts} posts from 'What's Hot Classic'...")
        all_posts = []
        cursor = None
        
        while len(all_posts) < max_posts:
            # Set the limit for this page, ensuring we don't fetch more than max_posts
            limit = min(100, max_posts - len(all_posts))
            if limit <= 0:
                break
            
            params = {
                "feed": WHATS_HOT_FEED_URI,
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor

            try:
                # This specific request does not require authentication, but we use
                # the authenticated request handler for consistency and future-proofing.
                response = self._make_request("GET", "app.bsky.feed.getFeed", params=params)
                
                posts_on_page = response.get('feed', [])
                if not posts_on_page:
                    print("No more posts found in the feed. Halting.")
                    break
                
                all_posts.extend(posts_on_page)
                print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")

                cursor = response.get('cursor')
                if not cursor:
                    print("Reached the end of the feed.")
                    break
                
                # Be a good citizen and don't spam the API too quickly
                time.sleep(1)

            except Exception as e:
                print(f"An error occurred during fetching: {e}")
                break
        
        return all_posts


if __name__ == "__main__":
    # --- Main Execution ---
    print("--- Bluesky Feed Fetcher ---")
    
    # Securely get user credentials
    user_handle = input("Enter your Bluesky handle (e.g., yourname.bsky.social): ")
    # IMPORTANT: For security, it is highly recommended to use an App Password.
    # You can create one in Bluesky under Settings -> App Passwords.
    app_password = input("Enter your App Password (will be visible): ")

    # 1. Create a session instance and log in
    session = BlueskySession(user_handle, app_password)
    if session.create_session():
        
        # NEW: Ask user for the number of posts to fetch
        while True:
            try:
                num_posts_to_fetch = int(input("Enter the total number of posts you want to fetch: "))
                if num_posts_to_fetch > 0:
                    break
                else:
                    print("Please enter a number greater than 0.")
            except ValueError:
                print("Invalid input. Please enter a whole number.")

        # 2. Fetch posts from the feed based on user input
        hot_posts = session.get_whats_hot_classic(max_posts=num_posts_to_fetch)
        
        print(f"\n✨ --- Fetching Complete --- ✨")
        print(f"Total posts retrieved: {len(hot_posts)}")

        # 3. Save the data to a uniquely named JSON file
        if hot_posts:
            # Create a unique filename with a timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"Trends_bluesky_{timestamp}.json"
            
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(hot_posts, f, ensure_ascii=False, indent=4)
                print(f"\n✅ Successfully saved {len(hot_posts)} posts to '{filename}'")
            except Exception as e:
                print(f"\n❌ Failed to save posts to file. Error: {e}")

        # 4. Display a few examples
        if hot_posts:
            print("\nHere are the first 3 posts retrieved:")
            for i, item in enumerate(hot_posts[:3]):
                post = item.get('post', {})
                author = post.get('author', {})
                record = post.get('record', {})
                text = record.get('text', '[No Text]').replace('\n', ' ')
                print(f"  {i+1}. @{author.get('handle', 'unknown')}: \"{text[:100]}...\"")
