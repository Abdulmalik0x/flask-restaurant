from flask import Flask
from http.server import BaseHTTPRequestHandler, HTTPServer
import cgi
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Restaurant, MenuItem, User
from flask import render_template, url_for, request, redirect, flash, jsonify
from flask import session as login_session
import random
import string

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests
import os

from elasticsearch import Elasticsearch

app = Flask(__name__)

# Connect to db and create db session
# this because sqlite require new thread for each transaction with DB
engine = create_engine('sqlite:///restaurantmenuwithusers.db',
                       connect_args={'check_same_thread': False})
""" MetaData object contains all of the schema constructs we’ve associated with it """
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


os.chdir("D:/Downloads/fsnd-virtual-machine/FSND-Virtual-Machine/vagrant/")
CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Restaurant Menu Application"


@app.route('/login')
def loginOauth():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in range(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)


@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # decode because content be like (b'value') which affect the url
    access_token = request.data.decode()
    print("access token received %s " % access_token)

    app_id = json.loads(open('fb_client_secrets.json', 'r').read())[
        'web']['app_id']
    app_secret = json.loads(open('fb_client_secrets.json', 'r').read())[
        'web']['app_secret']
    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (
        app_id, app_secret, access_token)
    h = httplib2.Http()
   # print ("App secret value : %s Value of url :  %s "  % (app_secret, url,)) # problem is access token insetion be like b'value'
    result = h.request(url, 'GET')[1]
    print(result)  # to see the result of url

    # Use token to get user info from API
    userinfo_url = "https://graph.facebook.com/v2.8/me"
    '''
        Due to the formatting for the result from the server token exchange we have to
        split the token first on commas and select the first index which gives us the key : value
        for the server access token then we split it on colons to pull out the actual token value
        and replace the remaining quotes with nothing so that it can be used directly in the graph
        api calls
    '''
    token = result.decode('utf8').split(',')[0].split(':')[1].replace(
        '"', '')  # decode('utf8') added to decode str to bytes

    url = 'https://graph.facebook.com/v2.8/me?access_token=%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    # print "url sent for API access:%s"% url
    print("API JSON result: %s" % result)
    data = json.loads(result)
    print("Api date : %s" % data)
    login_session['provider'] = 'facebook'
    login_session['username'] = data["name"]
    login_session['facebook_id'] = data["id"]
    try:
        login_session['email'] = data["email"]
    except:
        pass

    # The token must be stored in the login_session in order to properly logout
    login_session['access_token'] = token

    # Get user picture
    url = 'https://graph.facebook.com/v2.8/me/picture?access_token=%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    print("Returned result after consume access token : %s" % (result,))
    data = json.loads(result)
    print("After converting to json : %s" % (data,))

    login_session['picture'] = data["data"]["url"]

    print("Reach here")
    # see if user exists
    user_id = getUserId(login_session['email'])
    if not user_id:
        # not tested yet, may be need serialize
        user_id = createUser(login_session)
        print("User created")

    login_session['user_id'] = user_id
    print("login_session info after sign in : %s " % login_session)

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']

    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '

    flash("Now logged in as %s" % login_session['username'])
    return output


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token, compare logged session with request session
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token for user data is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])

    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print("Token's client ID does not match app's.")
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps('Current user is already connected.'),
                                 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    """ To check logged user have account in db, if not create one """
    email = login_session['email']
    try:
        print("email %s" % email)
        print("Query : %s" % session.query(
            User).filter_by(email=email).first())
        if session.query(User).filter_by(email=login_session['email']).one() is None:
            print("Not found")
        print("User already have accoun in database")
    except:
        print("Error Happened")
        createUser(login_session)
        print("New user has been added")

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print("done!")
    return output


@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print('Access Token is None')
        response = make_response(json.dumps(
            'Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    print('In gdisconnect access token is %s ' % access_token)
    print('User name is: ')
    print(login_session['username'])
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print('result is : ')
    print(result)
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(json.dumps(
            'Failed to revoke token for given user.'))
        response.headers['Content-Type'] = 'application/json'
    return response


def createUser(login_session):
  #  receivedEmail = login_session['email']
   # userName = receivedEmail.partition('@')[0]
    print("Here is login name " + login_session['username'])
    newUser = User(name=login_session['username'],
                   email=login_session['email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserId(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.serialize['id']
    except:
        return None


@app.route('/')
@app.route('/restaurant/')
def showRestaurants():
    if 'username' not in login_session:
        return redirect('/login')
    allRestaurants = session.query(Restaurant).all()
    print ("Reached here !")
    return render_template('restaurants.html', allRestaurants=allRestaurants)


@app.route('/restaurant/<int:restaurant_id>/')
def showMenu(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).first()
    items = session.query(MenuItem).filter_by(restaurant_id=restaurant_id)
    return render_template('restaurantmenu.html', restaurant=restaurant, items=items)


@app.route('/restaurant/addnewrestaurant/', methods=['GET', 'POST'])
def addRestaurant():
    if request.method == 'GET':
        return render_template('addnewrestaurant.html')
    else:
        print(request.form['restaurantname'])
        newRestaurant = Restaurant(
            name=request.form['restaurantname'], user_id=login_session['user_id'])
        session.add(newRestaurant)
        session.commit()
        return redirect(url_for('showRestaurants'))


@app.route('/restaurant/<int:restaurant_id>/newmenu', methods=['GET', 'POST'])
def newMenuItem(restaurant_id):
    print(login_session)
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newMenu = MenuItem(
            name=request.form['name'], restaurant_id=restaurant_id)
        session.add(newMenu)
        session.commit()
        flash("New menu item have added successfully!")
        return redirect(url_for('Menu', restaurant_id=restaurant_id))
    else:
        return render_template('newmenuitem.html', restaurant_id=restaurant_id)


@app.route('/restaurant/<int:restaurant_id>/<int:menu_id>/edit', methods=['GET', 'POST'])
def editMenuItem(restaurant_id, menu_id):
    editedItem = session.query(MenuItem).filter_by(
        id=menu_id, restaurant_id=restaurant_id,).one()
    if request.method == 'POST':

       # editedItem = MenuItem(name = request.form['newname'], restaurant_id = restaurant_id, id = menu_id)
        if request.form['newname']:
            editedItem.name = request.form['newname']
        session.add(editedItem)
      #  session.add(item)
        session.commit()
        flash("Menu item have edited successfully!")

        return redirect(url_for('showMenu', restaurant_id=restaurant_id))

    else:
     #   item = session.query(MenuItem).filter_by(restaurant_id = restaurant_id, id = menu_id).one()
        editedItem = session.query(MenuItem).filter_by(id=menu_id).one()
        return render_template('editmenuitem.html', restaurant_id=restaurant_id, menu_id=menu_id, item=editedItem)

# Task 3: Create a route for deleteMenuItem function here


@app.route('/restaurant/<int:restaurant_id>/<int:menu_id>/delete', methods=['GET', 'POST'])
def deleteMenuItem(restaurant_id, menu_id):
    deleteitem = session.query(MenuItem).filter_by(
        id=menu_id, restaurant_id=restaurant_id,).one()
    if request.method == 'POST':
        session.delete(deleteitem)
        session.commit()
        redirect(url_for('Menu', restaurant_id=restaurant_id))
    else:
        return render_template('deletemenuitem.html', restaurant_id=restaurant_id, menu_id=menu_id, item=deleteitem)

# Making API endpoint (GET Request)


@app.route('/restaurant/<int:restaurant_id>/menu/json')
def MenuItemJSON(restaurant_id):
  #  restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    items = session.query(MenuItem).all()
    return jsonify([i.MenuItemJSON for i in items])


@app.route('/restaurant/json')
def RestaurantsJSON():
  #  restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    Restaurants = session.query(Restaurant).all()
    return jsonify(Resturants=[i.RestaurantsJSON for i in Restaurants])


@app.route('/restaurant/search/', methods=['POST'])
def SearchRestaurant():
    if request.method == 'POST':
        searchWord = request.form['wordToSearch']
        restaurantToSearch = session.query(Restaurant).filter(Restaurant.name.ilike('%' + searchWord + '%')).all()
        """ The below functions is to implement the search using raw sql query, but now working yet """
      #  result11 = session.execute("SELECT * from Restaurant where name like '%' || :param || '%';", {'param': searchWord}) Fetch result but doesn't display
        #result2 = session.execute("SELECT Restaurant.id from Restaurant where Restaurant.name=%s;", (searchWord,))
        return render_template('restaurants.html', allRestaurants=restaurantToSearch)
    else : 
        return redirect('/Restaurant')


if __name__ == '__main__':
    # each session require secret key, to access the methods inside it like flash
    app.secret_key = 'super_secret_key'
    app.debug = True  # Auto reload for server if change occurs
    app.run(host='0.0.0.0', port=5050)
