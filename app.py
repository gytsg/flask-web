from flask import Flask
from flask import render_template,flash,redirect,session,url_for,request,g
from flask_login import login_user,logout_user,current_user,login_required
#from forms import LoginForm, EditForm
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from config import POSTS_PER_PAGE, MAX_SEARCH_RESULTS

app = Flask(__name__)
app.config.from_object('config')
db = SQLAlchemy(app)

# from flask_mail import Mail
# mail = Mail(app)

import models


#-login-#
import os
from flask_login import LoginManager
from flask_openid import OpenID
from config import basedir

lm = LoginManager()
lm.init_app(app)
lm.login_view = 'login'
oid = OpenID(app, os.path.join(basedir, 'tmp'))
@lm.user_loader
def load_user(id):
    from models import User
    #return User.query.get(int(id))
    return db.session.query(User).get(int(id))


@app.before_request
def before_request():
    from forms import SearchForm
    g.user = current_user
    if g.user.is_authenticated:
        g.user.last_seen = datetime.utcnow()
        db.session.add(g.user)
        db.session.commit()
        g.search_form = SearchForm()


from config import ADMINS,MAIL_SERVER,MAIL_PORT,MAIL_PASSWORD,MAIL_USERNAME

if not app.debug:
    import logging
    from logging.handlers import SMTPHandler
    credentials = None
    if MAIL_USERNAME or MAIL_PASSWORD:
        credentials = (MAIL_USERNAME, MAIL_PASSWORD)
    mail_handler = SMTPHandler((MAIL_SERVER, MAIL_PORT), 'no-reply@'+ MAIL_SERVER, ADMINS, 'microblog failure', credentials)
    mail_handler.setLevel(logging.ERROR)
    app.logger.addHandler(mail_handler)


if not app.debug:
    import logging
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler('tmp/microblog.log', 'a', 1*1024*1024, 10)
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    app.logger.setLevel(logging.INFO)
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.info('microblog startup')


@app.errorhandler(404)
def internal_error(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500


@app.route('/', methods=['GET', 'POST'])
@app.route('/index', methods=['GET', 'POST'])
@app.route('/index/<int:page>', methods=['GET', 'POST'])
@login_required
# def index():
#     user = {'nickname':'Miguel'}
#     return render_template("index.html",title = 'Home',user =user)
def index(page = 1):
    # user = {'nickname':'Miguel'}
    from forms import PostForm
    from models import Post
    user = g.user
    form = PostForm()
    if form.validate_on_submit():
        post = Post(body=form.post.data, timestamp=datetime.utcnow(), author=g.user)
        db.session.add(post)
        db.session.commit()
        flash('Your post is now live!')
        return redirect(url_for('index'))
    # posts = [
    #     {
    #         'author': {'nickname': 'john'},
    #         'body': 'Beautiful day in Portland!'
    #     },
    #     {
    #         'author': {'nickname': 'Susan'},
    #         'body': 'The Avengers movie was so cool!'
    #     }
    # ]
    # posts = g.user.followed_posts().paginate(page, POSTS_PER_PAGE, False).items
    posts = g.user.followed_posts().paginate(page, POSTS_PER_PAGE, False)
    return render_template('index.html',
                           title='Home',
                           form=form,
                           user=user,
                           posts=posts)


@app.route('/login', methods=['GET', 'POST'])
@oid.loginhandler
def login():
    from forms import LoginForm
    if g.user is not None and g.user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        session['remember_me'] = form.remember_me.data
        return oid.try_login(form.openid.data, ask_for=['nickname', 'email'])
    return render_template('login.html',
                           title = 'Sign In',
                           form = form,
                           providers = app.config['OPENID_PROVIDERS'])


@oid.after_login
def after_login(resp):
    from models import User
    if resp.email is None or resp.email == "":
        flash('Invalid login. Please try again.')
        return redirect(url_for('login'))
    user = User.query.filter_by(email=resp.email).first()
    if user is None:
        nickname = resp.nickname
        if nickname is None or nickname == "":
            nickname = resp.email.split('@')[0]
        nickname = User.make_unique_nickname(nickname)
        user = User(nickname=nickname, email=resp.email)
        db.session.add(user)
        db.session.commit()
        #make the user follow him/herself
        db.session.add(user.follow(user))
        db.session.commit()
    remember_me  = False
    if 'remember_me' in session:
        remember_me = session['remember_me']
        session.pop('remember_me',None)
    login_user(user, remember = remember_me)
    return redirect(request.args.get('next') or url_for('index'))


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/user/<nickname>')
@app.route('/user/<nickname>/<int:page>')
@login_required
def user(nickname, page=1):
    from models import User
    user = User.query.filter_by(nickname=nickname).first()
    if user is None:
        flash('User '+nickname+' not found.')
        return redirect(url_for('index'))
    # posts = [
    #     {'author':user, 'body': 'Test post #1'},
    #     {'author':user, 'body': 'Test post #2'}
    # ]
    # posts = user.posts.all()
    posts = user.posts.paginate(page, POSTS_PER_PAGE, False)
    return render_template('user.html',
                           user=user,
                           posts=posts)


@app.route('/edit', methods=['GET', 'POST'])
@login_required
def edit():
    from forms import EditForm
    form = EditForm(g.user.nickname)
    if form.validate_on_submit():
        g.user.nickname = form.nickname.data
        g.user.about_me = form.about_me.data
        db.session.add(g.user)
        db.session.commit()
        flash('Your changes have been saved.')
        return redirect(url_for('edit'))
    else:
        form.nickname.data = g.user.nickname
        form.about_me.data = g.user.about_me
    return render_template('edit.html', form=form)


@app.route('/follow/<nickname>')
@login_required
def follow(nickname):
    from models import User
    #user = User.query.filter_by(nickname=nickname).first()    //cause error : session conflict
    user = db.session.query(User).filter_by(nickname=nickname).first()
    if user is None:
        flash('User %s not found.' % nickname)
        return redirect(url_for('index'))
    if user == g.user:
        flash('You can\'t follow yourself!')
        return redirect(url_for('user',nickname = nickname))
    u = g.user.follow(user)
    if u is None:
        flash('Cannot follow '+nickname+ '.')
        return redirect(url_for('user',nickname=nickname))
    db.session.add(u)
    db.session.commit()
    flash('You are now following '+nickname+ '!')
    return redirect(url_for('user',nickname = nickname))


@app.route('/unfollow/<nickname>')
@login_required
def unfollow(nickname):
    from models import User
    #user = User.query.filter_by(nickname=nickname).first()    //cause error : session conflict
    user = db.session.query(User).filter_by(nickname=nickname).first()
    if user is None:
        flash('User %s not found.' % nickname)
        return redirect(url_for('index'))
    if user == g.user:
        flash('You can\'t unfollow yourself!')
        return redirect(url_for('user', nickname=nickname))
    u = g.user.unfollow(user)
    if u is None:
        flash('Cannot unfollow '+nickname+ '.')
        return redirect(url_for('user', nickname=nickname))
    db.session.add(u)
    db.session.commit()
    flash('You have stopped following '+nickname+'.')
    return redirect(url_for('user', nickname = nickname))


@app.route('/search', methods=['POST'])
@login_required
def search():
    if not g.search_form.validate_on_submit():
        return redirect(url_for('index'))
    return redirect(url_for('search_results', query=g.search_form.search.data))


@app.route('/search_results/<query>')
@login_required
def search_results(query):
    from models import Post
    results = Post.query.whoosh_search(query, MAX_SEARCH_RESULTS).all()
    return render_template('search_results.html',
                           query=query,
                           results=results)


if __name__ == '__main__':
    app.run(host='0.0.0.0',port=8000,threaded=True)
