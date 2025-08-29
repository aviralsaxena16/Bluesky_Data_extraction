#!/usr/bin/env python3
"""
Bluesky Custom Feed Archiver (updated)

Features / fixes:
- Robust HTTP error handling and safe JSON extraction
- Automatic token refresh on 401/ExpiredToken
- Better prompts & input cleaning
- Pagination with cursor and polite rate limiting
- Safer filename generation and clearer status messages
- Handles cases where responses have no JSON payload
"""

import requests
import os
import time
import json
import re
from datetime import datetime
from dotenv import load_dotenv

# --- Configuration ---
BSKY_HOST = "https://bsky.social"
REQUEST_RETRY_DELAY = 1.0  # seconds between paginated requests

def clean_input(input_string: str) -> str:
    """Remove non-printable characters and trim whitespace."""
    if input_string is None:
        return ""
    return ''.join(filter(str.isprintable, input_string)).strip()

def extract_at_uri(text: str):
    """
    Finds and returns the first at:// URI in the provided text.
    """
    if not text:
        return None
    match = re.search(r'(at://[^\s/]+(?:/[^\s/]+)*)', text)
    if match:
        return match.group(1)
    return None

def _safe_json(resp):
    """Attempt to return resp.json(), otherwise return an empty dict."""
    try:
        return resp.json()
    except ValueError:
        return {}

class BlueskySession:
    """
    Manages a session with the Bluesky API (access + refresh tokens, auto refresh).
    """

    def __init__(self, handle: str, password: str):
        self._handle = clean_input(handle)
        self._password = clean_input(password)
        self.access_jwt = None
        self.refresh_jwt = None
        self.did = None
        self.session_active = False

    def create_session(self) -> bool:
        """Create initial session using identifier + password (app password)."""
        print("Attempting to create a session...")
        try:
            resp = requests.post(
                f"{BSKY_HOST}/xrpc/com.atproto.server.createSession",
                json={"identifier": self._handle, "password": self._password},
                timeout=15,
            )
            if resp.status_code != 200:
                data = _safe_json(resp)
                msg = data.get("message") or data.get("error") or resp.text
                print(f"❌ Failed to create session (status {resp.status_code}): {msg}")
                return False

            data = _safe_json(resp)
            self.access_jwt = data.get("accessJwt")
            self.refresh_jwt = data.get("refreshJwt")
            self.did = data.get("did")
            self.session_active = bool(self.access_jwt)
            handle_returned = data.get("handle") or self._handle
            print(f"✅ Session created successfully for handle: {handle_returned}")
            return self.session_active
        except requests.RequestException as e:
            print(f"❌ Network error while creating session: {e}")
            return False

    def _refresh_session(self) -> bool:
        """Refresh access token using the refresh token."""
        print("\n⚠ Access token expired or invalid. Attempting refresh...")
        if not self.refresh_jwt:
            print("❌ No refresh token available. Cannot refresh session.")
            self.session_active = False
            return False
        try:
            resp = requests.post(
                f"{BSKY_HOST}/xrpc/com.atproto.server.refreshSession",
                headers={"Authorization": f"Bearer {self.refresh_jwt}"},
                timeout=15,
            )
            if resp.status_code != 200:
                data = _safe_json(resp)
                msg = data.get("message") or data.get("error") or resp.text
                print(f"❌ Refresh failed (status {resp.status_code}): {msg}")
                self.session_active = False
                return False
            data = _safe_json(resp)
            self.access_jwt = data.get("accessJwt")
            self.refresh_jwt = data.get("refreshJwt") or self.refresh_jwt
            self.session_active = bool(self.access_jwt)
            print("✅ Session refreshed successfully.")
            return self.session_active
        except requests.RequestException as e:
            print(f"❌ Network error during refresh: {e}")
            self.session_active = False
            return False

    def _make_request(self, method: str, xrpc_endpoint: str, params=None, json_data=None, headers=None, is_retry=False):
        """
        Generic authenticated request handler with automatic refresh on token expiry.
        Returns parsed JSON or raises an exception on unrecoverable errors.
        """
        if not self.session_active:
            raise Exception("Session is not active. Please create a session first.")
        
        if headers is None:
            headers = {}
        headers["Authorization"] = f"Bearer {self.access_jwt}"
        full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
        
        try:
            resp = requests.request(
                method, full_url,
                params=params, json=json_data,
                headers=headers, timeout=20
            )
            
            # If unauthorized or expired token, try refresh (commonly 401 or 400 with expired token)
            if resp.status_code in (401, 403):
                # Try refresh once
                if not is_retry and self._refresh_session():
                    return self._make_request(method, xrpc_endpoint, params=params, json_data=json_data, headers=headers, is_retry=True)
                else:
                    resp.raise_for_status()
            
            # Raise for other HTTP errors
            resp.raise_for_status()
            return _safe_json(resp)
        
        except requests.exceptions.HTTPError as e:
            data = _safe_json(e.response) if getattr(e, "response", None) else {}
            # if response indicates an expired token, attempt refresh (safety check)
            errcode = data.get("error") or data.get("code") or ""
            
            resp = getattr(e, "response", None)
            if not is_retry and resp:
                if resp.status_code in (400, 401) and ("Expired" in (errcode or "") or "Expired" in str(data).title()):
                    if self._refresh_session():
                        return self._make_request(method, xrpc_endpoint, params=params, json_data=json_data, headers=headers, is_retry=True)
            
            msg = data.get("message") or data.get("error") or (e.response.text if getattr(e, "response", None) else str(e))
            raise RuntimeError(f"HTTP error {getattr(e.response, 'status_code', 'N/A')}: {msg}") from e
        
        except requests.RequestException as e:
            raise RuntimeError(f"Network error: {e}") from e

    def discover_popular_feeds(self):
        """Fetch a list of popular feed generators (if available)."""
        print("\nDiscovering popular feeds...")
        try:
            data = self._make_request("GET", "app.bsky.unspecced.getPopularFeedGenerators")
            return data.get("feeds", []) if isinstance(data, dict) else []
        except Exception as e:
            print(f"Could not fetch popular feeds: {e}")
            return []

    def get_feeds_by_actor(self, actor_handle: str):
        """Fetch feeds created by a specific actor/handle."""
        actor_handle = clean_input(actor_handle)
        if not actor_handle:
            print("No actor handle provided.")
            return []
        print(f"\nFetching all feeds created by @{actor_handle}...")
        try:
            params = {"actor": actor_handle}
            data = self._make_request("GET", "app.bsky.feed.getActorFeeds", params=params)
            return data.get("feeds", []) if isinstance(data, dict) else []
        except Exception as e:
            print(f"Could not fetch feeds for {actor_handle}: {e}")
            return []

    def get_custom_feed(self, feed_uri: str, max_posts: int = 5000):
        """
        Fetch posts from a feed (uses pagination via cursor).
        Returns list of feed entries (raw response entries).
        """
        if not feed_uri:
            return []

        print(f"\nFetching up to {max_posts} posts from feed: {feed_uri}")
        all_posts = []
        cursor = None
        while len(all_posts) < max_posts:
            limit = min(100, max_posts - len(all_posts))
            if limit <= 0:
                break
            params = {"feed": feed_uri, "limit": limit}
            if cursor:
                params["cursor"] = cursor
            try:
                data = self._make_request("GET", "app.bsky.feed.getFeed", params=params)
                # `data` expected to be a dict containing 'feed' and optionally 'cursor'
                posts_on_page = data.get("feed") or []
                if not posts_on_page:
                    print("No more posts found in this feed. Halting.")
                    break
                all_posts.extend(posts_on_page)
                print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")
                cursor = data.get("cursor")
                if not cursor:
                    print("Reached the end of the feed.")
                    break
                time.sleep(REQUEST_RETRY_DELAY)
            except Exception as e:
                print(f"An error occurred during fetching: {e}")
                break
        return all_posts

def select_feed_from_list(feeds):
    """Display feeds with a safe name and prompt the user to choose."""
    if not feeds:
        print("No feeds found.")
        return None, None
    print("\n--- Please Select a Feed ---")
    for i, feed in enumerate(feeds):
        display_name = feed.get('displayName') or feed.get('name') or feed.get('uri') or f"Feed {i+1}"
        creator = (feed.get('creator') or {}).get('handle') if isinstance(feed.get('creator'), dict) else feed.get('creator')
        creator_str = f" (by @{creator})" if creator else ""
        print(f"[{i+1}] {display_name}{creator_str}")
    print("[0] Cancel")
    while True:
        try:
            choice = int(input("Enter the number of the feed you want to select: ").strip())
            if 0 <= choice <= len(feeds):
                if choice == 0:
                    print("Selection canceled.")
                    return None, None
                selected_feed = feeds[choice - 1]
                return selected_feed.get('uri'), (selected_feed.get('displayName') or selected_feed.get('name') or selected_feed.get('uri'))
            else:
                print("Invalid number. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")

def safe_filename(base: str):
    """Create a safe filename base (alphanumeric + underscores, trimmed)."""
    base = base or "feed"
    allowed = "_- .()[]"
    cleaned = "".join(c for c in base if c.isalnum() or c in allowed).strip()
    cleaned = cleaned.replace(" ", "_")[:40]
    return cleaned or "feed"

if __name__ == "__main__":
    load_dotenv()
    print("--- Bluesky Custom Feed Archiver ---")
    # user_handle = clean_input(input("Enter your Bluesky handle (identifier/email/handle): "))
    # app_password = clean_input(input("Enter your App Password (or account password if using that): "))

    user_handle = os.environ.get("BSKY_USERNAME")
    app_password = os.environ.get("BSKY_PASSWORD")
    session = BlueskySession(user_handle, app_password)
    if not session.create_session():
        print("Exiting due to session creation failure.")
        exit(1)

    target_uri = None
    feed_name = "custom_feed"

    while True:
        print("\nHow would you like to find a feed?")
        print("[1] Discover popular feeds on Bluesky")
        print("[2] List all feeds created by a specific user")
        print("[3] Enter a feed URL or AT URI directly")
        choice = clean_input(input("Enter your choice (1, 2, or 3): "))

        if choice == '1':
            popular_feeds = session.discover_popular_feeds()
            target_uri, feed_name = select_feed_from_list(popular_feeds)
            if target_uri:
                break
        elif choice == '2':
            creator_handle = clean_input(input("Enter the handle of the feed creator: "))
            if creator_handle:
                actor_feeds = session.get_feeds_by_actor(creator_handle)
                target_uri, feed_name = select_feed_from_list(actor_feeds)
                if target_uri:
                    break
        elif choice == '3':
            uri_input = clean_input(input("Enter the full feed URL or just the at:// URI: "))
            extracted_uri = extract_at_uri(uri_input)
            if extracted_uri:
                target_uri = extracted_uri
                feed_name = extracted_uri.split('/')[-1] if '/' in extracted_uri else extracted_uri
                break
            elif uri_input.startswith("at://"):
                target_uri = uri_input
                feed_name = uri_input.split('/')[-1] if '/' in uri_input else uri_input
                break
            else:
                # try to accept plain handle-like input (e.g. creator.feedName) rare; otherwise ask again
                print("Invalid input. Please provide a valid at:// URI or a URL that contains at://. Example: at://did:plc:xxxx/app.bsky.feed.generator/whats-hot")
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")

    if not target_uri:
        print("No feed selected. Exiting.")
        exit(0)

    # Ask number of posts
    while True:
        try:
            num_posts = int(clean_input(input(f"How many posts do you want to fetch from '{feed_name}'? (e.g., 500): ")))
            if num_posts > 0:
                break
            else:
                print("Please enter a number greater than 0.")
        except ValueError:
            print("Invalid input. Please enter a whole number.")

    # Fetch posts
    feed_posts = session.get_custom_feed(feed_uri=target_uri, max_posts=num_posts)
    print(f"\n✨ --- Fetching Complete --- ✨\nTotal posts retrieved from '{feed_name}': {len(feed_posts)}")

    if not feed_posts:
        print("No posts retrieved. Exiting.")
        exit(0)

    # Save to file
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_name = safe_filename(feed_name)
    filename = f"feed_{safe_name}_{timestamp}.json"
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(feed_posts, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Successfully saved {len(feed_posts)} posts to '{filename}'")
    except Exception as e:
        print(f"\n❌ Failed to save posts to file. Error: {e}")