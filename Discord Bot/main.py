# Loads stuff from .env and runs a Discord bot that can send messages to DeskBot ESP32 devices.
import discord
from discord import app_commands

# For logging discord events into a file. 
import logging

# Loads stuff so we can import data from .env.
from dotenv import load_dotenv
import os

# Loads stuff for the WebSocket server to communicate with the ESP32 devices. 
import asyncio
import json
import hmac
import ssl
import csv
import os.path
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

# Load env data. 
load_dotenv()

token = os.getenv("DISCORD_TOKEN")
guild_id = os.getenv("GUILD_ID")

# Validate required Discord credentials.
if not token:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

if not guild_id:
    raise RuntimeError("GUILD_ID is missing from .env")

guild = discord.Object(id=int(guild_id))

# Handles logs. 
handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")

# Loads intents. 
intents = discord.Intents.default()
intents.message_content = True

# Set client and tree for commands.
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Websocket
# ---

# SSL Certificate
def create_ssl_context() -> ssl.SSLContext:
    path = os.path.abspath(os.path.dirname(__file__)) # For relative path.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # Create self-signed certificates or obtain certificates from a CA and insert into /cert directory.
    ctx.load_cert_chain(path + "/cert/certificate.crt", path + "/cert/private.key")
    return ctx
ssl_ctx = create_ssl_context()

# Local WebSocket server addressing.
WS_HOST = "0.0.0.0"
WS_PORT = 8765

# Device Specific tokens loaded from .env.
DEVICE_TOKENS = {
    1: os.getenv("DEVICE_1_TOKEN"),
    2: os.getenv("DEVICE_2_TOKEN"),
    3: os.getenv("DEVICE_3_TOKEN"),
}

# For active WebSocket connections.
connected_devices = {}

# Prevents the server task being started multiple times. 
websocket_server_task = None

async def handle_device(websocket):
    # Authenticate a device and maintain its WebSocket connection.

    device_number = None

    try:
        # Wait for the device to send registration data within 10 seconds. 
        raw_registration = await asyncio.wait_for(websocket.recv(),timeout=10)

        registration = json.loads(raw_registration)

        # Device Number and Token. 
        device_number = int(registration["device"])
        supplied_token = str(registration["token"])

        expected_token = DEVICE_TOKENS.get(device_number)

        # Authenticate ESP32 device.
        if (
            expected_token is None
            or not hmac.compare_digest(
                supplied_token,
                expected_token
            )
        ):
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Authentication failed"
            }))

            await websocket.close(
                code=1008,
                reason="Unauthorized"
            )
            return

        # Close old connection if same device reconnects. 
        old_connection = connected_devices.get(device_number)

        if old_connection is not None and old_connection is not websocket:
            await old_connection.close(code=1000, reason="Device reconnected")

        # Save connection for this device number.
        connected_devices[device_number] = websocket

        print(f"Device {device_number} connected.")

        # ESP32 sends confirmation.
        await websocket.send(json.dumps({
            "type": "registered",
            "device": device_number
        }))

        # Keep the connection open
        async for raw_message in websocket:
            print(f"Message received from device " f"{device_number}: {raw_message}"
            )

    except asyncio.TimeoutError:
        print("A device did not register in time.")

    except (
        json.JSONDecodeError,
        KeyError,
        ValueError,
        TypeError
    ):
        print("A device sent invalid registration data.")

        await websocket.close(code=1008,reason="Invalid registration")

    except ConnectionClosed:
        pass

    finally:
        # Remove the connection only if it is still the current one.
        if (
            device_number is not None and connected_devices.get(device_number) is websocket):
            del connected_devices[device_number]
            print(f"Device {device_number} disconnected.")


# Start Websocket server
async def run_websocket_server():
    # Run the local WebSocket server until the bot shuts down.

    async with serve(handle_device, WS_HOST, WS_PORT, ssl=ssl_ctx):
        print(f"WebSocket server listening on " f"{WS_HOST}:{WS_PORT}")

        # Keep the server running.
        await asyncio.Future()


# Command
# ---

@tree.command(
    name="message",
    description="Send a message to a specific DeskBot device.",
    guild=guild
)
@app_commands.describe(
    device="The ESP32 device number to receive the message.",
    message="The message to display on the OLED."
)
async def send_device_message(
    interaction: discord.Interaction,
    device: int,
    message: str
) -> None:
    # Send a Discord message to one selected ESP32.

    # Ensure the selected device is configured.
    if device not in DEVICE_TOKENS:
        await interaction.response.send_message("Unknown device. Choose device 1, 2, or 3.", ephemeral=True)
        return

    # Do not allow blank or excessively long messages.
    message = message.strip()

    if not message:
        await interaction.response.send_message("Please enter a message.", ephemeral=True)
        return

    if len(message) > 500:
        await interaction.response.send_message("Messages must be 500 characters or fewer.", ephemeral=True)
        return

    # Check whether the requested ESP32 is connected.
    websocket = connected_devices.get(device)

    if websocket is None:
        await interaction.response.send_message(f"Device {device} is offline.",ephemeral=True)
        return

    # Format the message in the JSON structure expected by the ESP32.
    payload = {"type": "message","message": message}

    try:
        # Send only to the selected device.
        await websocket.send(json.dumps(payload))

        await interaction.response.send_message(f"Sent your message to DeskBot device {device}.",ephemeral=True)

        print(f"Discord message sent to device {device}.")

    except ConnectionClosed:
        # Remove the connection if it is no longer active.
        if connected_devices.get(device) is websocket:
            del connected_devices[device]

        await interaction.response.send_message(f"Device {device} disconnected before the message could be sent.",ephemeral=True)


# Sync command with discord
@client.event
async def on_ready():
    # Sync Discord commands and start the WebSocket server.

    global websocket_server_task

    # Register slash commands for the configured Discord server.
    await tree.sync(guild=guild)

    print("Discord commands have been synced!")
    print(f"Logged in as {client.user}")

    # Start the WebSocket server once.
    if (
        websocket_server_task is None or websocket_server_task.done()):
        websocket_server_task = asyncio.create_task(run_websocket_server())

# Run the bot
client.run(token, log_handler=handler, log_level=logging.DEBUG)