import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime
import requests, sys, json, time
from pathlib import Path

CONFIG_PATH = Path("config.json")
# Memory Cache:
# Keep tracked of already flagged islands
SEEN_ISLE_IDS = set()
scanCount = 0

def loadConfig():
    if not CONFIG_PATH.exists():
        print("Missing config.json. Copy config.example and fill it out.")
        sys.exit(1)
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)
config = loadConfig()
WEBHOOK_URL = config["webhook_url"]
TARGET_MIN_PRICE = config.get("target_min_price", 300)
POLL_INTERVAL_SECONDS = config.get("poll_interval_seconds", 40)
POLL_INTERVAL_MS = POLL_INTERVAL_SECONDS * 1000
USER_AGENT_STR = config["user_agent"]
HEADLESS = config.get("headless", False)
ALLOW_COUNT = config.get("allow_count", False)

def headlessLoop():
    try:
        app_log(f"System initialized. Radar sweeping target prices >= {TARGET_MIN_PRICE}...")
        while True:
            radarCycleOnce()
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        if ALLOW_COUNT:
            app_log(f"Shutdown requested. Total Completed Scans: {scanCount}")
        else:
            app_log("Shutdown requested. Exiting radar.")


def radarCycleOnce():
    raw_data = fetchRawListings()
    if not raw_data or "islands" not in raw_data:
        app_log("⚠️ Connection Error: Unable to reach endpoint.")
        return
    processFilter(raw_data)
    if ALLOW_COUNT:
        global scanCount 
        scanCount += 1
        if scanCount % 10 == 0:
            app_log(
                f"[System Log] Completed {scanCount} scans; "
                "Press Ctrl + C to stop the monitor."
            )
        elif scanCount % 5 == 0:
            app_log(
                f"[System Log] Completed {scanCount} scans."
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
        "category": "turnips",
        "islander": "daisy",
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
    current_time = datetime.now().strftime("%H:%M:%S")
    formatted_entry = f"[{current_time}] {message}\n"
    
    # Unlock box, append text, lock box to keep it tamper-proof, auto-scroll to bottom
    log_display.config(state=tk.NORMAL)
    log_display.insert(tk.END, formatted_entry)
    log_display.config(state=tk.DISABLED)
    log_display.see(tk.END)

def app_log(message):
    if HEADLESS:
        current_time = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{current_time}] {message}"
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
        splitTime = create_time.split(" ")
        date = splitTime[0] if len(splitTime) > 0 else "Unknown Date"
        timePost = splitTime[1] if len(splitTime) > 1 else "Unknown Time"
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
            if any(word in description for word in junk_words):
                # Print to terminal log to see filter is successful:
                app_log(f"[Filtered]Out]: Found {price} Bell island from {name}, but it had key junk words.")
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
                    f"**DESCRIPTION:** {description};"
                    f"**CURRENT QUEUE LENGTH:** {queued} players currently awaiting!\n"
                    f"*Posted on:* {date}; At {timePost}; \n"
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
    response = requests.post(WEBHOOK_URL, json=payload)

    # Verify HTTP Response Status
    # Discord returns a 204 No Content code on a flawless webhook transaction
    if response.status_code == 204:
        app_log(f"[🔥 ALERT SENT]: {name} is buying for {price}!")
    else:
        app_log(f"Failed to transmit data packet. Server returned code: {response.status_code}")
        app_log(response.text)

if HEADLESS:
    headlessLoop()
else:
    root = tk.Tk()
    root.title("Turnip Market Radar")
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

    windowLog(f"System Initialized. Radar sweeping target prices >= {TARGET_MIN_PRICE}...")
    root.after(1000, radarCycleGui)
    root.mainloop()