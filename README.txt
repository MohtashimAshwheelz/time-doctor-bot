HR AUDIT BOT — HANDOVER NOTES
================================

This is a slimmed-down version of the Odoo Bot for HR use.
It includes only the modules HR needs:

 - Audit Log     (fetch user activity, send WhatsApp reminders)
 - Settings      (Odoo credentials, TimeDoctor token, WhatsApp keys)
 - Debug Console (only for troubleshooting; usually not needed)


HOW TO LAUNCH
-------------
Double-click  run_hr.bat
(That's it. The bot will open.)


REQUIREMENTS
------------
The computer running this bot needs Python 3.10 or newer installed.
If running for the first time, the IT team should:

 1. Install Python from python.org
 2. During installation, tick "Add Python to PATH"
 3. Open Command Prompt in this folder, run:
       pip install -r requirements.txt
    (If there's no requirements.txt, ask the bot maintainer.)


FIRST-TIME SETUP
----------------
On first launch, the bot creates an empty config file: hr_config.json
Open the bot, click Settings (top right of Audit Log page), and fill in:

 - Odoo URL, database, username, password
 - Green API instance ID + token (for sending WhatsApp)
 - TimeDoctor email + password (or paste the API token directly)

Click Save in each section. Then test:
 - Click "Fetch ERP Data" → should populate the user list
 - Click "Fetch TD Data" → should populate TimeDoctor stats


DAILY USAGE
-----------
1. Open the bot (double-click run_hr.bat)
2. The Audit Log page is the only page shown
3. Select date (defaults to today)
4. Click "Fetch ERP Data" to get all users who logged activity
5. Click "Fetch TD Data" to get TimeDoctor stats (working hours, idle)
6. Combined report shows everyone — color-coded:
     red = high idle, amber = moderate idle, green = normal
7. Select users (Ctrl+click for multiple) to send reminders to
8. Click "Run Audit for Date" to send WhatsApp reminders


CONFIGURING THE MESSAGE
-----------------------
On the Audit Log page, there's a "Message Template" dropdown:
 - Standard, Urgent, Friendly templates come pre-loaded
 - Click "Edit" to modify any template
 - Click "Preview" to see how a user's message will read


DRILL-DOWN
----------
Double-click any user in the table to see their detailed activity:
 - Office Working / Office Idle / Extra Working / Work span
 - Idle breakdown: TD Summary, Per-instance gaps, Hourly breakdown
 - Activity intensity per idle period (keys/clicks/moves)
 - Suspicion score (0-100) for each idle instance


FILES IN THIS FOLDER
--------------------
 main.py            The bot code
 hr_config.json     Saved credentials (DO NOT SHARE)
 run_hr.bat         Double-click to launch
 README.txt         This file


TROUBLESHOOTING
---------------
If the bot won't launch:
 - Make sure Python is installed and in PATH
 - Make sure required packages are installed (see Requirements above)
 - Try opening Command Prompt in this folder and running:
      python main.py --hr
   This will show any error messages.

If the bot launches but pages are missing or look wrong:
 - Check that you're running the HR version
   (title bar should say "HR Audit Bot", logo should be 👥 not 📦)
 - If it says "Odoo Bot v5.4", the --hr flag isn't being passed —
   use run_hr.bat instead of double-clicking main.py

If credentials don't save:
 - Make sure hr_config.json isn't read-only
 - Make sure the folder is writable by the user

For any other issues, contact: [maintainer email/name]


SECURITY NOTES
--------------
 - hr_config.json contains credentials in plain text
 - Do not commit it to version control
 - Do not share it via email or chat
 - Keep this folder on a secure machine
