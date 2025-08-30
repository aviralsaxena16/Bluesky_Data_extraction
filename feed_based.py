#!/usr/bin/env python3
"""
Bluesky Custom Feed Archiver (Fully Upgraded)

Features:
- Fetches comments and replies for each post in parallel.
- Saves results to a dedicated 'feed_model' directory.
- Includes performance benchmarking and timestamp filtering.
- Retains all original feed discovery and selection features.
- Adds a clickable 'post_url' to each post object.
"""

import requests
import os
import time
import json
import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# --- Configuration ---
BSKY_HOST = "https://bsky.social"
MAX_COMMENTS_PER_POST = 150
MAX_WORKERS = 10

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
            resp.raise_for_status()
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
            resp.raise_for_status()
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
        """
        if not self.session_active:
            raise Exception("Session is not active. Please create a session first.")
        
        if headers is None: headers = {}
        headers["Authorization"] = f"Bearer {self.access_jwt}"
        full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
        
        try:
            resp = requests.request(
                method, full_url,
                params=params, json=json_data,
                headers=headers, timeout=20
            )
            resp.raise_for_status()
            return _safe_json(resp)
        except requests.exceptions.HTTPError as e:
            data = _safe_json(e.response) if getattr(e, "response", None) else {}
            errcode = data.get("error") or ""
            if not is_retry and ("ExpiredToken" in errcode):
                if self._refresh_session():
                    return self._make_request(method, xrpc_endpoint, params, json_data, headers, is_retry=True)
            msg = data.get("message") or str(e)
            raise RuntimeError(f"HTTP error {getattr(e.response, 'status_code', 'N/A')}: {msg}") from e
        except requests.RequestException as e:
            raise RuntimeError(f"Network error: {e}") from e

    def get_post_thread(self, post_uri):
        """Fetches a post's full thread, including comments and their replies."""
        try:
            params = {"uri": post_uri, "depth": 2}
            data = self._make_request("GET", "app.bsky.feed.getPostThread", params=params)
            return data.get('thread', {})
        except Exception as e:
            print(f"Error fetching thread for {post_uri}: {e}")
            return None

    def discover_popular_feeds(self):
        """Fetch a list of popular feed generators."""
        print("\nDiscovering popular feeds...")
        try:
            data = self._make_request("GET", "app.bsky.unspecced.getPopularFeedGenerators")
            return data.get("feeds", [])
        except Exception as e:
            print(f"Could not fetch popular feeds: {e}")
            return []

    def get_feeds_by_actor(self, actor_handle: str):
        """Fetch feeds created by a specific actor/handle."""
        actor_handle = clean_input(actor_handle)
        if not actor_handle: return []
        print(f"\nFetching all feeds created by @{actor_handle}...")
        try:
            params = {"actor": actor_handle}
            data = self._make_request("GET", "app.bsky.feed.getActorFeeds", params=params)
            return data.get("feeds", [])
        except Exception as e:
            print(f"Could not fetch feeds for {actor_handle}: {e}")
            return []

    def get_custom_feed(self, feed_uri: str, max_posts: int):
        """Fetch posts from a feed using pagination."""
        if not feed_uri: return []
        print(f"\nFetching up to {max_posts} posts from feed: {feed_uri}")
        all_posts = []
        cursor = None
        while len(all_posts) < max_posts:
            limit = min(100, max_posts - len(all_posts))
            if limit <= 0: break
            params = {"feed": feed_uri, "limit": limit}
            if cursor: params["cursor"] = cursor
            try:
                data = self._make_request("GET", "app.bsky.feed.getFeed", params=params)
                posts_on_page = data.get("feed") or []
                if not posts_on_page:
                    print("No more posts found in this feed. Halting.")
                    break
                
                for post in posts_on_page:
                    post['comments'] = []

                all_posts.extend(posts_on_page)
                print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")
                cursor = data.get("cursor")
                if not cursor:
                    print("Reached the end of the feed.")
                    break
                time.sleep(0.5)
            except Exception as e:
                print(f"An error occurred during fetching: {e}")
                break
        return all_posts

def select_feed_from_list(feeds):
    """Display feeds and prompt the user to choose."""
    if not feeds:
        print("No feeds found.")
        return None, None
    print("\n--- Please Select a Feed ---")
    for i, feed in enumerate(feeds):
        display_name = feed.get('displayName', f"Feed {i+1}")
        creator = (feed.get('creator') or {}).get('handle', 'unknown')
        print(f"[{i+1}] {display_name} (by @{creator})")
    print("[0] Cancel")
    while True:
        try:
            choice = int(input("Enter the number of the feed: ").strip())
            if 0 <= choice <= len(feeds):
                if choice == 0: return None, None
                selected = feeds[choice - 1]
                return selected.get('uri'), selected.get('displayName')
            else:
                print("Invalid number.")
        except ValueError:
            print("Invalid input.")

def safe_filename(base: str):
    """Create a safe filename base."""
    base = base or "feed"
    cleaned = "".join(c for c in base if c.isalnum() or c in " _-").strip()
    return cleaned.replace(" ", "_")[:40] or "feed"

def fetch_comments_and_replies(post_item):
    """Wrapper function for threading."""
    post_uri = post_item.get('post', {}).get('uri')
    if not post_uri: return post_item
    print(f"   Fetching comments for post: {post_uri.split('/')[-1]}")
    thread = session.get_post_thread(post_uri)
    if thread and 'replies' in thread:
        for comment_thread in thread['replies'][:MAX_COMMENTS_PER_POST]:
            comment_post = comment_thread.get('post', {})
            structured_comment = {"post": comment_post, "replies": []}
            if 'replies' in comment_thread:
                for reply_thread in comment_thread['replies']:
                    structured_comment["replies"].append(reply_thread.get('post', {}))
            post_item['comments'].append(structured_comment)
    return post_item

if __name__ == "__main__":
    load_dotenv()
    print("--- Bluesky Custom Feed Archiver (Upgraded) ---")
    user_handle = os.environ.get("BSKY_USERNAME")
    app_password = os.environ.get("BSKY_PASSWORD")

    global session
    session = BlueskySession(user_handle, app_password)
    if not session.create_session():
        exit(1)

    target_uri, feed_name = None, "custom_feed"
    while True:
        print("\nHow would you like to find a feed?")
        print("[1] Discover popular feeds")
        print("[2] List feeds by a specific user")
        print("[3] Enter a feed URI directly")
        choice = clean_input(input("Enter your choice (1, 2, or 3): "))
        if choice == '1':
            target_uri, feed_name = select_feed_from_list(session.discover_popular_feeds())
            if target_uri: break
        elif choice == '2':
            creator_handle = clean_input(input("Enter the feed creator's handle: "))
            if creator_handle:
                target_uri, feed_name = select_feed_from_list(session.get_feeds_by_actor(creator_handle))
                if target_uri: break
        elif choice == '3':
            uri_input = clean_input(input("Enter the full feed URL or at:// URI: "))
            extracted = extract_at_uri(uri_input) or (uri_input if uri_input.startswith("at://") else None)
            if extracted:
                target_uri = extracted
                feed_name = extracted.split('/')[-1]
                break
            else:
                print("Invalid input. Please provide a valid at:// URI.")
        else:
            print("Invalid choice.")

    if not target_uri:
        print("No feed selected. Exiting.")
        exit(0)

    num_posts_input = clean_input(input(f"How many posts to fetch from '{feed_name}'? (e.g., 500): "))
    num_posts = int(num_posts_input) if num_posts_input.isdigit() else 500

    print("\n--- Starting Benchmark ---")
    total_start_time = time.time()

    post_fetch_start = time.time()
    feed_posts = session.get_custom_feed(feed_uri=target_uri, max_posts=num_posts)
    post_fetch_end = time.time()
    print(f"--- 📊 Fetched {len(feed_posts)} initial posts in {post_fetch_end - post_fetch_start:.2f} seconds ---")

    start_time, end_time = None, None
    filter_choice = clean_input(input("\nDo you want to filter posts by timestamp? (y/n): ")).lower()
    if filter_choice == 'y':
        try:
            start_input = clean_input(input("Enter start timestamp (YYYY-MM-DD HH:MM:SS, blank for none): "))
            end_input = clean_input(input("Enter end timestamp (YYYY-MM-DD HH:MM:SS, blank for none): "))
            if start_input: start_time = datetime.strptime(start_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if end_input: end_time = datetime.strptime(end_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            print("⚠️ Invalid date format. Aborting.")
            exit(1)

    final_posts = []
    if filter_choice == 'y':
        print("\nFiltering posts by timestamp...")
        for post in feed_posts:
            created_at_str = post.get('post', {}).get('record', {}).get('createdAt')
            if created_at_str:
                post_time = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                if (start_time is None or post_time >= start_time) and (end_time is None or post_time <= end_time):
                    final_posts.append(post)
        print(f"--- Filtered down to {len(final_posts)} posts. ---")
    else:
        final_posts = feed_posts
        
    # --- NEW: Add clickable URL to each post ---
    print("\nGenerating clickable URLs for posts...")
    for item in final_posts:
        post_data = item.get('post', {})
        author_handle = post_data.get('author', {}).get('handle')
        post_uri = post_data.get('uri')
        if author_handle and post_uri:
            post_id = post_uri.split('/')[-1]
            item['post']['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

    if final_posts:
        print(f"\nFetching comments for {len(final_posts)} posts using {MAX_WORKERS} parallel workers...")
        comment_fetch_start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(fetch_comments_and_replies, final_posts))
        comment_fetch_end = time.time()
        print(f"--- 📊 Fetched comments in {comment_fetch_end - comment_fetch_start:.2f} seconds ---")
        final_posts = results

    total_end_time = time.time()
    print(f"\n✨ --- Total Execution Time: {total_end_time - total_start_time:.2f} seconds --- ✨")

    if final_posts:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = safe_filename(feed_name)
        output_dir = "feed_model"
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, f"feed_{safe_name}_{timestamp}.json")
        
        print(f"\nSaving {len(final_posts)} posts to '{filename}'...")
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(final_posts, f, ensure_ascii=False, indent=2)
            print(f"\n✅ Successfully saved results.")
        except Exception as e:
            print(f"\n❌ Failed to save to file. Error: {e}")