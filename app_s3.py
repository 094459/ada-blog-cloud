from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import uuid
import boto3
from botocore.exceptions import ClientError
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_for_testing')

# RDS PostgreSQL connection configuration
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'xxxx')
DB_HOST = os.environ.get('DB_HOST', 'xxxx')  # Your RDS endpoint
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'xxx')

# PostgreSQL connection string
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# S3 configuration
S3_BUCKET = os.environ.get('S3_BUCKET', 'xxxx')
S3_REGION = os.environ.get('S3_REGION', 'eu-west-1')
S3_PROFILE_IMAGES_PREFIX = 'profile-images/'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max upload size

# Initialize S3 client
s3_client = boto3.client('s3', region_name=S3_REGION)

db = SQLAlchemy(app)

# Association tables
upvotes = db.Table('upvotes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id'), primary_key=True)
)

user_follows = db.Table('user_follows',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('created_at', db.DateTime, default=datetime.utcnow)
)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    alias = db.Column(db.String(100), nullable=False)
    bio = db.Column(db.String(250), nullable=True)
    profile_image = db.Column(db.String(255), nullable=True)  # Now stores S3 object key
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    posts = db.relationship('Post', backref='author', lazy='dynamic', foreign_keys='Post.author_id')
    responses = db.relationship('Post', backref='responder', lazy='dynamic', foreign_keys='Post.responder_id')
    upvoted_posts = db.relationship('Post', secondary=upvotes, backref=db.backref('upvoters', lazy='dynamic'))
    
    # Following relationship
    following = db.relationship(
        'User', secondary=user_follows,
        primaryjoin=(user_follows.c.follower_id == id),
        secondaryjoin=(user_follows.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'),
        lazy='dynamic'
    )
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def follow(self, user):
        if not self.is_following(user):
            self.following.append(user)
            
    def unfollow(self, user):
        if self.is_following(user):
            self.following.remove(user)
            
    def is_following(self, user):
        return self.following.filter(user_follows.c.followed_id == user.id).count() > 0
    
    def followed_posts(self):
        return Post.query.join(
            user_follows, (user_follows.c.followed_id == Post.author_id)
        ).filter(user_follows.c.follower_id == self.id)
    
    def get_profile_image_url(self):
        """Generate a pre-signed URL for the user's profile image"""
        if not self.profile_image:
            return None
        
        try:
            url = s3_client.generate_presigned_url('get_object',
                                                  Params={'Bucket': S3_BUCKET,
                                                          'Key': self.profile_image},
                                                  ExpiresIn=3600)  # URL expires in 1 hour
            return url
        except ClientError as e:
            logging.error(f"Error generating presigned URL: {e}")
            return None

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)  # PostgreSQL uses Text type without length limit
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    responder_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    parent_post = db.relationship('Post', remote_side=[id], backref='responses')
    images = db.relationship('Image', backref='post', lazy='dynamic')
    links = db.relationship('Link', backref='post', lazy='dynamic')

class Image(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    image_url = db.Column(db.String(255), nullable=False)  # Now stores S3 object key
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def get_image_url(self):
        """Generate a pre-signed URL for the image"""
        try:
            url = s3_client.generate_presigned_url('get_object',
                                                  Params={'Bucket': S3_BUCKET,
                                                          'Key': self.image_url},
                                                  ExpiresIn=3600)  # URL expires in 1 hour
            return url
        except ClientError as e:
            logging.error(f"Error generating presigned URL: {e}")
            return None

class Link(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    url = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Helper function to count total replies (including nested replies)
def count_total_replies(post):
    """Recursively count all replies to a post, including nested replies."""
    direct_responses = Post.query.filter_by(parent_id=post.id).all()
    count = len(direct_responses)
    
    for response in direct_responses:
        count += count_total_replies(response)
    
    return count

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def upload_file_to_s3(file, prefix=''):
    """Upload a file to S3 bucket and return the object key"""
    if file and allowed_file(file.filename):
        # Create a unique filename to prevent overwriting
        filename = secure_filename(file.filename)
        unique_filename = f"{prefix}{uuid.uuid4().hex}_{filename}"
        
        try:
            s3_client.upload_fileobj(file, S3_BUCKET, unique_filename)
            return unique_filename
        except ClientError as e:
            logging.error(f"Error uploading file to S3: {e}")
            return None
    return None

def delete_file_from_s3(object_key):
    """Delete a file from S3 bucket"""
    if not object_key:
        return False
    
    try:
        s3_client.delete_object(Bucket=S3_BUCKET, Key=object_key)
        return True
    except ClientError as e:
        logging.error(f"Error deleting file from S3: {e}")
        return False

@app.route('/')
def index():
    sort_by = request.args.get('sort_by', 'newest')
    filter_by = request.args.get('filter_by', 'all')
    
    if sort_by == 'newest':
        posts_query = Post.query.order_by(Post.created_at.desc())
    else:  # oldest
        posts_query = Post.query.order_by(Post.created_at.asc())
    
    # Filter by followed users if user is logged in
    if filter_by == 'followed' and 'user_id' in session:
        current_user = User.query.get(session['user_id'])
        if current_user:
            posts_query = current_user.followed_posts().order_by(
                Post.created_at.desc() if sort_by == 'newest' else Post.created_at.asc()
            )
    
    posts = posts_query.all()
    
    # Calculate total replies for each post (including nested replies)
    for post in posts:
        post.total_replies_count = count_total_replies(post)
        # Generate S3 URLs for images
        for image in post.images:
            image.s3_url = image.get_image_url()
        # Generate S3 URL for author's profile image
        if post.author.profile_image:
            post.author.profile_image_url = post.author.get_profile_image_url()
    
    return render_template('index.html', posts=posts, sort_by=sort_by, filter_by=filter_by)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        alias = request.form['alias']
        bio = request.form.get('bio', '')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'danger')
            return render_template('register.html')
        
        user = User(email=email, alias=alias, bio=bio)
        user.set_password(password)
        
        # Handle profile image upload to S3
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file.filename != '':
                s3_object_key = upload_file_to_s3(file, S3_PROFILE_IMAGES_PREFIX)
                if s3_object_key:
                    user.profile_image = s3_object_key
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/profile/<int:user_id>')
def profile(user_id):
    user = User.query.get_or_404(user_id)
    posts = Post.query.filter_by(author_id=user_id).order_by(Post.created_at.desc()).all()
    follower_count = user.followers.count()
    
    # Get profile image URL from S3
    profile_image_url = user.get_profile_image_url()
    
    # Calculate total replies for each post (including nested replies)
    for post in posts:
        post.total_replies_count = count_total_replies(post)
        # Generate S3 URLs for images
        for image in post.images:
            image.s3_url = image.get_image_url()
    
    is_following = False
    if 'user_id' in session:
        current_user = User.query.get(session['user_id'])
        if current_user:
            is_following = current_user.is_following(user)
    
    return render_template('profile.html', user=user, posts=posts, 
                          follower_count=follower_count, is_following=is_following,
                          profile_image_url=profile_image_url)

@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        flash('Please login to edit your profile', 'danger')
        return redirect(url_for('login'))
    
    user = User.query.get_or_404(session['user_id'])
    
    if request.method == 'POST':
        user.alias = request.form['alias']
        user.bio = request.form.get('bio', '')
        
        # Handle profile image upload to S3
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file.filename != '':
                # Delete old profile image from S3 if it exists
                if user.profile_image:
                    delete_file_from_s3(user.profile_image)
                
                # Upload new profile image to S3
                s3_object_key = upload_file_to_s3(file, S3_PROFILE_IMAGES_PREFIX)
                if s3_object_key:
                    user.profile_image = s3_object_key
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile', user_id=user.id))
    
    # Get profile image URL from S3
    profile_image_url = user.get_profile_image_url()
    
    return render_template('edit_profile.html', user=user, profile_image_url=profile_image_url)

@app.route('/follow/<int:user_id>')
def follow(user_id):
    if 'user_id' not in session:
        flash('Please login to follow users', 'danger')
        return redirect(url_for('login'))
    
    current_user = User.query.get_or_404(session['user_id'])
    user_to_follow = User.query.get_or_404(user_id)
    
    if current_user.id == user_to_follow.id:
        flash('You cannot follow yourself', 'danger')
    else:
        current_user.follow(user_to_follow)
        db.session.commit()
        flash(f'You are now following {user_to_follow.alias}', 'success')
    
    return redirect(url_for('profile', user_id=user_id))

@app.route('/unfollow/<int:user_id>')
def unfollow(user_id):
    if 'user_id' not in session:
        flash('Please login to unfollow users', 'danger')
        return redirect(url_for('login'))
    
    current_user = User.query.get_or_404(session['user_id'])
    user_to_unfollow = User.query.get_or_404(user_id)
    
    current_user.unfollow(user_to_unfollow)
    db.session.commit()
    flash(f'You have unfollowed {user_to_unfollow.alias}', 'success')
    
    return redirect(url_for('profile', user_id=user_id))

@app.route('/new_post', methods=['GET', 'POST'])
def new_post():
    if 'user_id' not in session:
        flash('Please login to create a post', 'danger')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        content = request.form['content']
        parent_id = request.form.get('parent_id')
        
        post = Post(
            content=content,
            author_id=session['user_id'],
            parent_id=parent_id if parent_id else None,
            responder_id=session['user_id'] if parent_id else None
        )
        
        db.session.add(post)
        db.session.commit()
        
        # Handle links
        if 'link_url' in request.form and request.form['link_url']:
            link = Link(
                post_id=post.id,
                url=request.form['link_url'],
                title=request.form.get('link_title', '')
            )
            db.session.add(link)
        
        # Handle image uploads to S3
        if 'image_file' in request.files:
            file = request.files['image_file']
            if file.filename != '':
                s3_object_key = upload_file_to_s3(file, 'post-images/')
                if s3_object_key:
                    image = Image(
                        post_id=post.id,
                        image_url=s3_object_key
                    )
                    db.session.add(image)
        # Handle image URLs
        elif 'image_url' in request.form and request.form['image_url']:
            image = Image(
                post_id=post.id,
                image_url=request.form['image_url']
            )
            db.session.add(image)
        
        db.session.commit()
        flash('Post created successfully!', 'success')
        return redirect(url_for('index'))
    
    parent_id = request.args.get('parent_id')
    parent_post = None
    if parent_id:
        parent_post = Post.query.get_or_404(parent_id)
        # Generate profile image URL for parent post author
        if parent_post.author.profile_image:
            parent_post.author.profile_image_url = parent_post.author.get_profile_image_url()
    
    return render_template('new_post.html', parent_post=parent_post)

@app.route('/upvote/<int:post_id>')
def upvote(post_id):
    if 'user_id' not in session:
        flash('Please login to upvote posts', 'danger')
        return redirect(url_for('login'))
    
    user = User.query.get_or_404(session['user_id'])
    post = Post.query.get_or_404(post_id)
    
    if post in user.upvoted_posts:
        user.upvoted_posts.remove(post)
        flash('Upvote removed', 'info')
    else:
        user.upvoted_posts.append(post)
        flash('Post upvoted!', 'success')
    
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/view_post/<int:post_id>')
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    responses = Post.query.filter_by(parent_id=post_id).order_by(Post.created_at.asc()).all()
    
    # Calculate total replies for the main post (including nested replies)
    post.total_replies_count = count_total_replies(post)
    
    # Calculate total replies for each response
    for response in responses:
        response.total_replies_count = count_total_replies(response)
    
    # Get image URLs from S3 for the post and responses
    for image in post.images:
        image.s3_url = image.get_image_url()
    
    # Get profile image URL for the post author
    if post.author.profile_image:
        post.author.profile_image_url = post.author.get_profile_image_url()
    
    for response in responses:
        for image in response.images:
            image.s3_url = image.get_image_url()
        # Get profile image URL for each response author
        if response.author.profile_image:
            response.author.profile_image_url = response.author.get_profile_image_url()
    
    return render_template('view_post.html', post=post, responses=responses)

@app.context_processor
def utility_processor():
    def get_current_user():
        if 'user_id' in session:
            return User.query.get(session['user_id'])
        return None
    
    return {'get_current_user': get_current_user}

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
