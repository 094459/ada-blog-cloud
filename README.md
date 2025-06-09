# MicroBlog Application

A simple microblogging application built with Flask, based on the data model defined in `data-model/micro-blogging.yaml`.

## Features

- User registration and authentication
- User profiles with customizable alias and bio
- Timeline of posts with sorting options (newest/oldest)
- Filter posts by followed users
- Follow/unfollow other users
- Create, view, and upvote posts
- Reply to posts and view threaded conversations
- Add links and images to posts
- Edit user profile information

## Data Model

The application uses the following data model:

- **User**: Stores user information including email, alias, and optional bio
- **Post**: Contains post content (up to 1024 characters), with support for responses
- **Image**: Stores image URLs associated with posts
- **Link**: Stores links associated with posts
- **Upvotes**: Tracks which users have upvoted which posts
- **User Follows**: Tracks user follow relationships

## Installation

1. Clone the repository
2. Install dependencies:
   ```
   pip install flask flask-sqlalchemy
   ```
3. Run the application:
   ```
   python app.py
   ```

## Usage

1. Register a new account
2. Create posts from the homepage
3. View and edit your profile
4. Follow other users
5. Upvote and reply to posts

## Project Structure

```
/
├── app.py                 # Main application file
├── data-model/            # Data model definitions
│   ├── micro-blogging.yaml    # YAML data model
│   └── micro-blogging-erd.svg # ERD diagram
└── templates/             # HTML templates
    ├── base.html          # Base template with layout
    ├── index.html         # Homepage/timeline
    ├── profile.html       # User profile page
    ├── edit_profile.html  # Edit profile page
    ├── login.html         # Login page
    ├── register.html      # Registration page
    ├── new_post.html      # Create new post page
    └── view_post.html     # View single post with replies
```