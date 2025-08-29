# Bluesky Data Extraction Suite

This repository contains a suite of Python scripts designed to extract and archive public data from the Bluesky social network. The tools allow for targeted data collection based on search terms, user profiles, trending feeds, and custom community feeds.

Each script is designed to fetch not only the primary posts but also the associated comments and replies, saving the structured data into JSON files for further analysis.

---

## 🔑 Key Features

-   **Parallel Processing:** All scripts use a `ThreadPoolExecutor` to fetch comments for multiple posts simultaneously, significantly speeding up data collection.
-   **Comment & Reply Fetching:** Each model retrieves up to 150 comments for every post, along with the replies to those comments.
-   **Direct Post URLs:** A clickable `post_url` is added to each post object in the final JSON output, allowing for easy navigation to the original post on the Bluesky web app.
-   **JSON Output:** All data is saved in a structured JSON format in dedicated directories (`search_model`, `user_model`, etc.), making it easy to parse and use in other applications.

---

## ⚙️ The Models & Authentication Strategy

After extensive testing, a hybrid authentication approach is required for maximum performance and reliability.

### 🔓 Unauthenticated Models (Recommended for these tasks)

These scripts connect to Bluesky's public API and do not require you to log in. They are fast and efficient for their specific purpose.

-   **`user_based_unauth.py`**:
    -   **Function:** Fetches the post history of one or more Bluesky users and also the comments and their replies.
    -   **Performance:** Works flawlessly without authentication and performs identically to the authenticated version.

-   **`feed_based_unauth.py`**:
    -   **Function:** Discovers, selects, and archives posts from simple, custom feeds.
    -   **Performance:** Works perfectly for most custom feeds. Fails on complex algorithmic feeds (see below).

### 🔒 Authenticated Models (Required for these tasks)

These scripts require you to log in with your Bluesky handle and an App Password. They are necessary to bypass server security and technical limitations.

-   **`search_based.py`**:
    -   **Reason:** **Authentication is mandatory.** The public search endpoint has aggressive anti-bot security that consistently blocks unauthenticated scripts with a `403 Forbidden` error.
    -   **Function:** Searches the entire Bluesky network for posts matching a query, with options to exclude terms and sort by "Top" or "Latest".

-   **`trend_based.py`**:
    -   **Reason:** **Authentication is required for deep scans.** The "What's Hot Classic" feed uses a highly complex cursor for pagination. After ~600 posts, this cursor becomes too long, causing the public server to return a `414 URI Too Long` error. The authenticated script does not have this limitation.
    -   **Function:** Fetches posts that are currently trending on the network.

---

## 💡 Understanding the "Cursor"

The reliability of unauthenticated fetching depends on the "cursor" used for pagination.

-   **Simple Cursors:** For simple requests like a user's timeline, the cursor is short (likely a timestamp/post ID). The unauthenticated public API handles these without issue.
-   **Complex Cursors:** For algorithmic feeds ("What's Hot," "Discover"), the cursor is an extremely long, alphanumeric string that encodes the complex state of the algorithm. These long cursors will cause errors on the public API but work with the authenticated version.

---

## 🚀 Setup & Usage

1.  **Create Credentials File:** In the root directory, create a file named `.env` and add your Bluesky handle and an App Password. This is only needed for the authenticated scripts.
    ```
    USERNAME=yourhandle.bsky.social
    PASSWORD=xxxx-xxxx-xxxx-xxxx
    ```

2.  **Run a Script:** Execute any of the Python scripts from your terminal. You will be prompted for input based on the script's function.
    ```bash
    # For a search, which requires login
    python search_based.py

    # For fetching a user's posts, which does not require login
    python user_based_unauth.py
    ```