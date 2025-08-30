from datetime import datetime, timezone, date
import requests
import os
import time
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# --- Configuration ---
BSKY_HOST = "https://bsky.social"
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

    def search_posts_advanced(self, query, sort_order='latest', max_posts=1000):
        """
        Performs an advanced search for posts with pagination.
        """
        print(f"\nSearching for posts with query: '{query}' (sorted by {sort_order})")
        print(f"Fetching up to {max_posts} posts...")
        
        all_posts = []
        cursor = None
        
        while len(all_posts) < max_posts:
            limit = min(100, max_posts - len(all_posts))
            if limit <= 0:
                break

            params = {"q": query, "sort": sort_order, "limit": limit}
            if cursor:
                params["cursor"] = cursor

            try:
                response = self._make_request("GET", "app.bsky.feed.searchPosts", params=params)
                posts_on_page = response.get('posts', [])
                if not posts_on_page:
                    print("No more posts found for this search. Halting.")
                    break
                
                for post in posts_on_page:
                    post['comments'] = []
                
                all_posts.extend(posts_on_page)
                print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")

                cursor = response.get('cursor')
                # print(cursor)
                if not cursor:
                    print("Reached the end of the search results.")
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
    post_uri = post_item.get('uri') # Search results have a different structure
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
    print("--- Bluesky Advanced Discovery Tool (Upgraded) ---")
    
    user_handle = os.environ.get("BSKY_USERNAME")
    app_password = os.environ.get("BSKY_PASSWORD")

    global session
    session = BlueskySession(user_handle, app_password)

    if session.create_session():
        print("\n--- Build Your Search Query ---")
        
        include_terms = clean_input(input('Enter search terms (use "quotes for exact phrases"): '))
        exclude_terms_raw = clean_input(input('Enter words to EXCLUDE (optional, separate with spaces): '))
        exclude_terms = [f"-{term.strip()}" for term in exclude_terms_raw.split() if term.strip()]
        
        final_query_parts = [include_terms] + exclude_terms
        final_query = " ".join(final_query_parts).strip()
        
        if not final_query:
            print("No search query provided. Exiting.")
            exit()

        while True:
            sort_choice = clean_input(input("Sort by [1] Top or [2] Latest? (Enter 1 or 2): "))
            if sort_choice == '1':
                sort_order = 'top'
                break
            elif sort_choice == '2':
                sort_order = 'latest'
                break
            else:
                print("Invalid choice. Please enter 1 or 2.")
        
        num_posts_input = clean_input(input("How many posts do you want to fetch? (e.g., 500): "))
        num_posts = int(num_posts_input) if num_posts_input.isdigit() else 500

        print("\n--- Starting Benchmark ---")
        total_start_time = time.time()

        # --- 1. Fetching Posts ---
        post_fetch_start = time.time()
        fetched_posts = session.search_posts_advanced(final_query, sort_order, num_posts)
        post_fetch_end = time.time()
        print(f"--- 📊 Fetched {len(fetched_posts)} posts in {post_fetch_end - post_fetch_start:.2f} seconds ---")

        # --- 2. Filtering ---
        final_posts = []
        lang_choice = clean_input(input("\nFilter by language? (Enter 2-letter code like 'en', 'es', or leave blank for all): ")).lower()
        if not lang_choice:
            final_posts = fetched_posts
        else:
            for post in fetched_posts:
                langs = post.get('record', {}).get('langs', [])
                if langs and lang_choice in langs:
                    final_posts.append(post)
            print(f"Filtered down to {len(final_posts)} posts in language '{lang_choice}'.")

        ts_filter_choice = clean_input(input("\nDo you want to filter by date? (y/n): ")).lower()
        if ts_filter_choice == 'y':
            try:
                lower_limit_str = clean_input(input("Enter start date (YYYY-MM-DD, blank for no limit): ")).strip()
                upper_limit_str = clean_input(input("Enter end date (YYYY-MM-DD, blank for no limit): ")).strip()

                # --- CORRECTED LOGIC ---
                # Use date objects for a direct and clear comparison.
                lower_limit_date = date.fromisoformat(lower_limit_str) if lower_limit_str else date.min
                upper_limit_date = date.fromisoformat(upper_limit_str) if upper_limit_str else date.max

                filtered_by_time = []
                for post in final_posts:
                    created_at_str = post.get('record', {}).get('createdAt')
                    if created_at_str:
                        post_date = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")).date()
                        if lower_limit_date <= post_date <= upper_limit_date:
                            filtered_by_time.append(post)
                
                print(f"Filtered down to {len(filtered_by_time)} posts by date.")
                final_posts = filtered_by_time
            except ValueError:
                print("⚠️ Invalid date format. Please use YYYY-MM-DD.")
        
        # --- Add clickable URL to each post ---
        print("\nGenerating clickable URLs for posts...")
        for item in final_posts:
            # Note: Search results have a slightly different structure
            author_handle = item.get('author', {}).get('handle')
            post_uri = item.get('uri')
            if author_handle and post_uri:
                post_id = post_uri.split('/')[-1]
                item['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

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
            safe_query = "".join(c for c in final_query if c.isalnum() or c in (' ', '_')).rstrip()
            safe_query = safe_query.replace(' ', '_')[:30]

            output_dir = "search_model"
            os.makedirs(output_dir, exist_ok=True)
            filename = os.path.join(output_dir, f"search_{safe_query}_{timestamp}.json")
            
            print(f"\nSaving {len(final_posts)} posts with comments to '{filename}'...")
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(final_posts, f, ensure_ascii=False, indent=2)
                print(f"\n✅ Successfully saved results.")
            except Exception as e:
                print(f"\n❌ Failed to save posts to file. Error: {e}")