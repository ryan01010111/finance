import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    user = session["user_id"]

    # get symbols of all shares owned by current user, and quantity of those shares owned
    userShares = db.execute("SELECT symbol, quantity FROM shares WHERE user_id = :user AND quantity > 0",
                            user=user)

    # set counter for user's total value of assets (shares + cash)
    userTotal = 0

    # look up and add the current price of each symbol to its respective dictionary
    for row in userShares:
        shareData = lookup(row['symbol'])
        row['name'] = shareData['name']
        row['price'] = float(shareData['price'])
        userTotal += row['quantity'] * row['price']

    userCash = db.execute("SELECT cash FROM users WHERE id = :user",
                            user=user)[0]['cash']
    userTotal += userCash

    return render_template("index.html", userShares=userShares, userCash=userCash, userTotal=userTotal)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    if request.method == "POST":

        symbol = request.form.get("symbol").upper()
        # ensure symbol was submitted
        if not symbol:
            return apology("You must enter a symbol", 403)

        # ensure symbol was submitted and symbol exists
        shareData = lookup(symbol)
        if not shareData:
            return apology("That symbol couldn't be found", 403)

        # ensure "shares" field not empty
        if not request.form.get("shares"):
            return apology("You must enter a valid quantity of shares", 403)

        shares = int(request.form.get("shares"))
        # ensure "shares" input is a positive integer
        if shares < 1:
            return apology("You must enter a valid quantity of shares", 403)

        user = session["user_id"]
        price = shareData["price"]
        purchaseTotal = price * shares
        rows = db.execute("SELECT * FROM users WHERE id = :user",
                            user=user)

        cash = rows[0]["cash"]

        # ensure that current user has sufficient cash on account
        if cash < purchaseTotal:
            return apology("You don't have enough funds for this purchase", 403)

        else:
            # update user's cash amount (charge the purchase amount)
            db.execute("UPDATE users SET cash = :cash WHERE id = :user",
                        cash=cash - purchaseTotal, user=user)

            # insert transaction data into "transactions" table
            db.execute("INSERT INTO transactions (user_id, type, symbol, price, quantity) VALUES (:user, 'buy', :symbol, :price, :quantity)",
                        user=user, symbol=symbol, price=price, quantity=shares)

            ## update number of shares owned in "shares" table

            sharesPair = db.execute("SELECT * FROM shares WHERE user_id = :user AND symbol = :symbol",
                        user=user, symbol=symbol)

            # check if user/symbol pair exists - if not, inserts the pair and sets quantity of shares owned
            if len(sharesPair) != 1:
                db.execute("INSERT INTO shares (user_id, symbol, quantity) VALUES (:user, :symbol, :quantity)",
                            user=user, symbol=symbol, quantity=shares)

            # if pair already exists, updates that pair with new quantity of shares owned
            else:
                # sets new amount of shares owned by the user
                newQuantity = sharesPair[0]["quantity"] + shares
                db.execute("UPDATE shares SET quantity = :newQuantity WHERE user_id = :user AND symbol = :symbol",
                            newQuantity=newQuantity, user=user, symbol=symbol)

                flash("Buy order complete!")

        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    user = session["user_id"]
    # select relevant transaction data
    userTransactions = db.execute("SELECT type, symbol, price, quantity, timestamp FROM transactions WHERE user_id = :user ORDER BY id DESC",
                                    user=user)

    return render_template("history.html", userTransactions=userTransactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    if request.method == "POST":

        # request data on requested symbol
        quoteData = lookup(request.form.get("symbol"))

        if not quoteData:
            return render_template("quoted.html", quoteData=quoteData, symbol=request.form.get("symbol"))
        else:
            return render_template("quoted.html", quoteData=quoteData)

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        # ensure username was submitted
        if not username:
            return apology("must provide username", 403)

        # ensure password was submitted
        elif not password:
            return apology("must provide password", 403)

        # ensure confirmation was submitted
        elif not confirmation:
            return apology("must provide confirmation", 403)

        # check that username doesn't already exist
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                                username=username)

        if len(rows) == 1:
            return apology("that username already exists", 403)

        elif password != confirmation:
            return apology("password and confirmation do not match", 403)

        else:
            ## credit referring account and create registering user's account

            # if referral code used, credit $100 to referring user's account
            referral_code = request.form.get("referral")
            if referral_code:
                # search submitted referral code for matching user, and get that user's cash amount
                referring_user_cash = db.execute("SELECT cash FROM users WHERE referral_code = :referral_code",
                                                    referral_code=referral_code)

                # if previous search for user returned no match, alert registering user
                if len(referring_user_cash) != 1:
                    flash("That referral code doesn't match a registered user")
                    return redirect("/register")

                # if referring user found, add $100 to referring user's account
                newCash = referring_user_cash[0]['cash'] + 100
                db.execute("UPDATE users SET cash = :newCash WHERE referral_code = :referral_code",
                            newCash=newCash, referral_code=referral_code)

            # create user account
            db.execute("INSERT INTO users (username, hash, referral_code) VALUES (:username, :hash, :referral_code)",
                        username=username, hash=generate_password_hash(password), referral_code='rp-'+username)

            # set session for user and log in
            session["user_id"] = db.execute("SELECT id FROM users WHERE username = :username",
                                                username=username)[0]['id']
            flash("Registered successfully! Welcome to CS50 Finance!")
            return redirect("/")

    else:
        return render_template("register.html")

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    user = session['user_id']

    if request.method == "POST":

        symbol = request.form.get("symbol")
        # ensure symbol was selected - NOTE: input of "Symbol" is default and has no value
        if symbol == "Symbol":
            return apology("You must select a symbol", 403)

        # ensure "shares" field not empty
        if not request.form.get("shares"):
            return apology("You must enter a valid quantity of shares", 403)

        shares = int(request.form.get("shares"))
        # ensure "shares" input is a positive integer
        if shares < 1:
            return apology("You must enter a valid quantity of shares", 403)

        sharesHeld = int(db.execute("SELECT quantity FROM shares WHERE user_id = :user AND symbol = :symbol",
                        user=user, symbol=symbol)[0]['quantity'])
        # ensure user has sufficient shares to sell
        if shares > sharesHeld:
            return apology("The quantity entered exceeds the number of shares available", 403)

        # update user's number of shares held
        db.execute("UPDATE shares SET quantity = :quantity WHERE user_id = :user AND symbol = :symbol",
                    quantity=sharesHeld - shares, user=user, symbol=symbol)

        price = lookup(symbol)['price']
        userCash = db.execute("SELECT cash FROM users WHERE id = :user",
                                user=user)[0]['cash']

        newCash = userCash + (shares * price)
        # update user's cash amount
        db.execute("UPDATE users SET cash = :newCash WHERE id = :user",
                    newCash=newCash, user=user)

        # update transactions table
        db.execute("INSERT INTO transactions (user_id, type, symbol, price, quantity) VALUES (:user, 'sell', :symbol, :price, :quantity)",
                    user=user, symbol=symbol, price=price, quantity=shares)

        flash("Sell order complete!")
        return redirect("/")

    else:
        return render_template("sell.html", userSymbols=db.execute("SELECT symbol FROM shares WHERE user_id = :user AND quantity > 0",
                                user=user))


@app.route("/referral")
@login_required
def referral():
    """Get referral code"""

    user = session["user_id"]

    # get user's referral code
    referral_code = db.execute("SELECT referral_code FROM users WHERE id = :user",
                user=user)[0]['referral_code']

    # display Referral Program page with user's referral code
    return render_template("referral.html", referral_code=referral_code)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
