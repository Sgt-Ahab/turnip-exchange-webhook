import tkinter as tk
from tkinter import scrolledtext, messagebox
from datetime import datetime
import requests, sys, json, time
from pathlib import Path

CONFIG_PATH = Path("config.json")
# Memory Cache:
# Keep tracked of already flagged islands
SEEN_ISLE_IDS = set()
scanCount = 0
wipeCount = 0
totalIDsWipedinSession = 0
lastCacheClearTime = time.time()

def loadConfig():
    if not CONFIG_PATH.exists():
        err_text = "Missing config.json. Copy config.example and fill it out."
        print(err_text)
        # Fallback dialog if launched silently via pythonw
        try:
            from tkinter import messagebox
            messagebox.showerror("Configuration Missing", err_text)
        except Exception:
            pass
        sys.exit(1)
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as e:
        err_syntax = f"Configuration Error: config.json contains invalid syntax;\nReason: {e}"
        print(f"[System Log]: {err_syntax}")
        try:
            from tkinter import messagebox
            messagebox.showerror("Configuration Syntax Error", err_syntax)
        except Exception:
            pass
        sys.exit(1)

config = loadConfig()
WEBHOOK_URL = config["webhook_url"]
TARGET_MIN_PRICE = config.get("target_min_price", 300)
POLL_INTERVAL_SECONDS = config.get("poll_interval_seconds", 40)
POLL_INTERVAL_MS = int(POLL_INTERVAL_SECONDS * 1000)
USER_AGENT_STR = config["user_agent"]
HEADLESS = config.get("headless", False)
ALLOW_COUNT = config.get("allow_count", False)
SAVE_LOG = config.get("save_log", False)
# This is what island category to search for on the site
CATEGORY = config.get("category", "turnips")
# Which villager to select
ISLANDER = config.get("islander", "daisy")

def headlessLoop():
    try:
        app_log(f"System initialized. Radar sweeping target prices >= {TARGET_MIN_PRICE}...")
        while True:
            radarCycleOnce()
            time.sleep(POLL_INTERVAL_SECONDS)
    except (KeyboardInterrupt, SystemExit): 
        if ALLOW_COUNT or SAVE_LOG:
            app_log(f"[System Log]: Headless-Shutdown requested. Total Completed Scans: {scanCount}")
        else:
            app_log("[System Log]: Headless-Shutdown requested. Exiting radar.")


def radarCycleOnce():
    global lastCacheClearTime, totalIDsWipedinSession
    
    # Cache Cycle (4-Hour Rule)
    currentTime = time.time()
    if currentTime - lastCacheClearTime >= 14400: # 14400 = 4 hours; +/- 3600 per hour
        wipedThisCycle = len(SEEN_ISLE_IDS)
        totalIDsWipedinSession += wipedThisCycle
        SEEN_ISLE_IDS.clear()
        app_log(f"[System Log]: Time threshold met, memory cleared out {wipedThisCycle} entries. (Total Wiped: {totalIDsWipedinSession})")
        lastCacheClearTime = currentTime

    raw_data = fetchRawListings()
    if not raw_data or "islands" not in raw_data:
        app_log("⚠️ Connection Error: Unable to reach endpoint.")
        return
    processFilter(raw_data)

    if ALLOW_COUNT:
        global scanCount 
        scanCount += 1
        if scanCount % 10 == 0:
            log_msg = f"[System Log]: Completed {scanCount} scans."
            if HEADLESS:
                log_msg += " Press Ctrl + C to stop the monitor."
            else:
                log_msg += " Close the window to stop the monitor."
            app_log(log_msg)
        elif scanCount % 5 == 0:
            app_log(
                f"[System Log]: Completed {scanCount} scans."
            )
def radarCycleGui():
    radarCycleOnce()
    root.after(POLL_INTERVAL_MS, radarCycleGui)

def fetchRawListings():
    # API Call for Island Data
    req_url = "https://api.turnip.exchange/islands/"
    # Request Method is POST
    headers = {
        "User-Agent": USER_AGENT_STR,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    query_payload = {
        "category": CATEGORY,
        "islander": ISLANDER,
    }
    try:
        response = requests.post(req_url, headers=headers, json=query_payload, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        app_log(f"[⚠ Connection Error]: Unable to fetch datapool; Reason: {e}")
    return None

def windowLog(message):
    """Prefixes the log string with local machine time and injects it into the text panel."""
    global wipeCount
    current_time = datetime.now().strftime("%H:%M:%S")
    log_display.config(state=tk.NORMAL)
    # 1,000 Line Threshold Data Compaction Logic
    try:
        current_lines = int(log_display.index('end-1c').split('.')[0])
        # This line is the line check for clearing the buffer
        if current_lines > 1000:
            wipeCount += 1
            log_display.delete("1.0", tk.END)
            total_lines_cleared = wipeCount * 1000
            log_display.insert(tk.END, f"[System Log]: Buffer cleared. [Wipe #{wipeCount} | ~ {total_lines_cleared} lines condensed!]\n")
    except Exception:
        pass
    formatted_entry = f"[{current_time}] {message}\n"
    
    # Unlock box, append text, lock box to keep it tamper-proof, auto-scroll to bottom
    log_display.insert(tk.END, formatted_entry)
    log_display.config(state=tk.DISABLED)
    log_display.see(tk.END)

def app_log(message):
    current_time = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{current_time}] {message}"

    # Hard-Drive Storage Stream Ouput (Parsing Logs)
    if SAVE_LOG:
        try:
            with open("session_log.txt", "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass

    if HEADLESS:
        print(formatted)
    else:
        windowLog(message)

def processFilter(data):
    # Normalization & Rules
    if not data or "islands" not in data:
        return
    
    for island in data["islands"]:
        # Extract unique identity and primary parameters
        turnip_code = island.get("turnipCode")
        price = island.get("turnipPrice", 0)
        name = island.get("name", "")
        description = island.get("description", "").lower()
        queued = island.get("queued")
        create_time = island.get("creationTime", "")
        if create_time and " " in create_time:
            splitTime = create_time.split(" ")
            date = splitTime[0] 
            timePost = splitTime[1]
        else:
            date ="Unknown Date"
            timePost ="Unknown Time"
        # create_time = island.get("creationTime")
        if turnip_code == "00000000" or name == "No Islands": 
            app_log(
                f"[🟢 Connection Verified]: Received {len(data['islands'])} room(s). || "
                f"On standby for met thresholds."
                )
            continue
        # 1st Check, if in cache IDs:
        if turnip_code in SEEN_ISLE_IDS:
            continue

        # Check 2, is it genuine high, or is this capped at site max?
        if TARGET_MIN_PRICE <= price <= 660:

            # Check 3, remove Twitch and Treasure Islands
            junk_words = ["twitch", "stream", "treasure", "sub", "t.v", "youtube"]
            if any(word.lower() in description for word in junk_words):
                # Print to terminal log to see filter is successful:
                app_log(f"[Filtered Out]: Found {price} Bell island from {name}, but it had key junk words.")
                SEEN_ISLE_IDS.add(turnip_code)
                continue

            # If through to here, it can be moved to next step
            marketAlert(name, price, queued, turnip_code, description, date, timePost)
            SEEN_ISLE_IDS.add(turnip_code)

def marketAlert(name, price, queued, turnip_code, description="No description provided.", date="Unknown Date", timePost="Unknown Time"):
    """
    Creates a payload dictionary and transmit to Discord Server
    """
    payload = {
        "username": "Daisy Mae's Turnip Radar",
        "avatar_url": "https://dodo.ac/np/images/f/f8/Daisy_Mae_NH_Character_Icon.png",
        "embeds":[
            {
                "title": f"📈 Stalk Market Spike on {name}'s Island!",
                "description": (
                    f"**PRICE:** {price} Bells per turnip.\n"
                    f"**DESCRIPTION:** {description};\n"
                    f"**CURRENT QUEUE LENGTH:** {queued} players currently awaiting!\n"
                    f"*Posted on: {date}; At {timePost}*; \n"
                    f"[Click Here to Join the Queue](https://turnip.exchange/island/{turnip_code})\n\n"
                    
                ),
                "color": 5763719, # Decimal -> Emerald Green
                "thumbnail":{
                    "url": "https://dodo.ac/np/images/f/f8/Daisy_Mae_NH_Character_Icon.png",
                },
                "footer": {
                    "text": "Sgt-Ahab Turnips.exchange Notifier",
                },
            }
        ]
    }
    # Ship the data block over the web
    # Passing the dict to the 'json=' parameter automatically converts it and sets the header
    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)

        # Verify HTTP Response Status
        # Discord returns a 204 No Content code on a flawless webhook transaction
        if response.status_code == 204:
            app_log(f"[System Log]: FOUND ISLAND! {name} is buying for {price}!")
        else:
            app_log(f"[System Log]: Failed to transmit data packet. Server returned code: {response.status_code}")
            app_log(response.text)
    except Exception as e:
        app_log(f"[System Log]: Failed to dispatch secure webhook payload links: {e}")

def loadIcon(path):
    # Finding the Asset image of Daisy for icon
    try:
        return tk.PhotoImage(file=path)
    except Exception as e:
        messagebox.showerror("Icon Loading Error...\n", f" Failed to load icon: {e}")
        return None

def closeWindow():
    if messagebox.askokcancel("Exit", "Do you want to exit Turnip Radar?"):
        if ALLOW_COUNT or SAVE_LOG:
            app_log(f"[System Log]: Windowed-Shutdown requested. Total Completed Scans: {scanCount}")
        else:
            app_log("[System Log]: Windowed-Shutdown requested. Exiting radar.")
        root.destroy()    
if HEADLESS:
    headlessLoop()
else:
    
    root = tk.Tk()
    root.title("Turnip Market Radar")
    daisyPhoto = loadIcon("assets/daisy.png")
    if daisyPhoto:
        try:
            root.iconphoto(True, daisyPhoto)
        except Exception as e:
            messagebox.showerror("Icon Loading Error...\n", f"Failed to set icon: {e}")
    root.geometry("700x300")
    root.configure(bg="#1e1e1e")

    log_display = scrolledtext.ScrolledText(
        root,
        wrap=tk.WORD,
        bg="#121212",
        fg="#00FF66",
        font=("Consolas", 10),
        state=tk.DISABLED
    )
    log_display.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    app_log(f"[System Log]: Radar Initialized. Radar sweeping target prices >= {TARGET_MIN_PRICE}...")
    root.after(1000, radarCycleGui)
    root.protocol("WM_DELETE_WINDOW", closeWindow)
    root.mainloop()