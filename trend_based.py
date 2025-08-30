from datetime import datetime, timezone
import requests
import os
import time
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
# --- Configuration ---
BSKY_HOST = "https://bsky.social"
WHATS_HOT_FEED_URI = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"
# Maximum number of comments to fetch for each post
MAX_COMMENTS_PER_POST = 150 
# Number of parallel workers for fetching comments
MAX_WORKERS = 10 

def clean_input(input_string):
    """
    A robust function to remove all non-printable characters from a string.
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

    def get_post_thread(self, post_uri):
        """
        Fetches a post's full thread, including comments and their replies.
        """
        try:
            params = {"uri": post_uri, "depth": 2} # Depth 2 gets comments and their replies
            data = self._make_request("GET", "app.bsky.feed.getPostThread", params=params)
            return data.get('thread', {})
        except Exception as e:
            print(f"Error fetching thread for {post_uri}: {e}")
            return None

    def get_whats_hot_classic(self, max_posts):
        """
        Fetches posts from the 'What's Hot Classic' feed using pagination.
        """
        print(f"\nFetching up to {max_posts} posts from 'What's Hot Classic'...")
        all_posts = []
        cursor = None
        
        while len(all_posts) < max_posts:
            limit = min(100, max_posts - len(all_posts))
            if limit <= 0:
                break
            
            params = {"feed": WHATS_HOT_FEED_URI, "limit": limit}
            if cursor:
                params["cursor"] = cursor

            try:
                response = self._make_request("GET", "app.bsky.feed.getFeed", params=params)
                posts_on_page = response.get('feed', [])
                if not posts_on_page:
                    print("No more posts found in the feed. Halting.")
                    break
                
                for post in posts_on_page:
                    post['comments'] = []

                all_posts.extend(posts_on_page)
                print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")

                cursor = response.get('cursor')
                if not cursor:
                    print("Reached the end of the feed.")
                    break
                
                time.sleep(0.5) # Polite delay

            except Exception as e:
                print(f"An error occurred during fetching: {e}")
                break
        
        return all_posts

# This function will be run in parallel for each post
def fetch_comments_and_replies(post_item):
    """
    Wrapper function for threading. Fetches comments and replies for a single post.
    """
    post_uri = post_item.get('post', {}).get('uri')
    if not post_uri:
        return post_item

    print(f"   Fetching comments for post: {post_uri.split('/')[-1]}")
    thread = session.get_post_thread(post_uri)
    
    if thread and 'replies' in thread:
        top_level_comments = thread['replies']
        
        for comment_thread in top_level_comments[:MAX_COMMENTS_PER_POST]:
            comment_post = comment_thread.get('post', {})
            structured_comment = {"post": comment_post, "replies": []}

            if 'replies' in comment_thread:
                for reply_thread in comment_thread['replies']:
                    structured_comment["replies"].append(reply_thread.get('post', {}))
            
            post_item['comments'].append(structured_comment)

    return post_item


if __name__ == "__main__":
    load_dotenv()
    print("--- Bluesky Trending Feed Archiver (Upgraded) ---")
    
    user_handle = os.environ.get("BSKY_USERNAME")
    app_password = os.environ.get("BSKY_PASSWORD")

    global session
    session = BlueskySession(user_handle, app_password)

    if session.create_session():
        num_posts_input = clean_input(input("How many trending posts do you want to fetch? (e.g., 500): "))
        num_posts = int(num_posts_input) if num_posts_input.isdigit() else 500

        start_time, end_time = None, None
        filter_choice = clean_input(input("\nDo you want to filter posts by timestamp? (y/n): ")).lower()
        if filter_choice == 'y':
            try:
                start_input = clean_input(input("Enter start timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
                end_input = clean_input(input("Enter end timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
                if start_input:
                    start_time = datetime.strptime(start_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if end_input:
                    end_time = datetime.strptime(end_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                print("⚠️ Invalid date format. Please use YYYY-MM-DD HH:MM:SS. Aborting.")
                exit(1)
        
        print("\n--- Starting Benchmark ---")
        total_start_time = time.time()

        # --- 1. Fetching Posts ---
        post_fetch_start = time.time()
        hot_posts = session.get_whats_hot_classic(max_posts=num_posts)
        post_fetch_end = time.time()
        print(f"--- 📊 Fetched {len(hot_posts)} initial posts in {post_fetch_end - post_fetch_start:.2f} seconds ---")

        # --- 2. Filtering Posts by Timestamp ---
        final_posts = []
        if filter_choice == 'y':
            print("\nFiltering posts by timestamp...")
            for post in hot_posts:
                created_at_str = post.get('post', {}).get('record', {}).get('createdAt')
                if created_at_str:
                    post_time = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    if (start_time is None or post_time >= start_time) and \
                       (end_time is None or post_time <= end_time):
                        final_posts.append(post)
            print(f"--- Filtered down to {len(final_posts)} posts in the selected time range. ---")
        else:
            final_posts = hot_posts
            
        # --- NEW: Add clickable URL to each post ---
        print("\nGenerating clickable URLs for posts...")
        for item in final_posts:
            post_data = item.get('post', {})
            author_handle = post_data.get('author', {}).get('handle')
            post_uri = post_data.get('uri')
            if author_handle and post_uri:
                post_id = post_uri.split('/')[-1]
                item['post']['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

        # --- 3. Fetching Comments in Parallel ---
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

        # --- 4. Saving Results ---
        if final_posts:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            
            output_dir = "trending_model"
            os.makedirs(output_dir, exist_ok=True)
            filename = os.path.join(output_dir, f"trending_whats-hot_{timestamp}.json")
            
            print(f"\nSaving {len(final_posts)} posts with comments to '{filename}'...")
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(final_posts, f, ensure_ascii=False, indent=2)
                print(f"\n✅ Successfully saved results.")
            except Exception as e:
                print(f"\n❌ Failed to save posts to file. Error: {e}")