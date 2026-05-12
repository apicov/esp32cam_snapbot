import asyncio
import base64
from io import BytesIO
from urllib.parse import urlparse

# external dependencies
from PIL import Image
import paho.mqtt.client as mqtt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import yaml


async def send_photo_async(chat_id, img_bytes):
    """
    Send the IMAGE_BYTES as a photo to the given CHAT_ID.
    """
    try:
        await app.bot.send_photo(chat_id, img_bytes, caption='Received Image')
        print(f"{chat_id}: The snapshot was sent to the requester")
    except Exception as e:
        print(f"{chat_id}: ERROR sending snapshot: {e}")


def on_message(client, userdata, message):
    """
    This function is called when the there's an incoming MESSAGE
    from the MQTT CLIENT. If the message is an image, then that
    image forwarded
    """
    if message.topic != MQTT_TOPIC_IMG:
        print(f'Incoming MQTT message from unsupported topic {message.topic}')
        return

    # Prepare the image to bytes for sending via Telegram
    img_bytes = BytesIO()

    # Decode base64 to get JPEG data
    jpeg_data = base64.b64decode(message.payload)

    # Open JPEG image and convert to send via Telegram
    img = Image.open(BytesIO(jpeg_data))
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)

    # XXX: Without a retry mechanism, then it's OK to drop the
    # chat_id from the snap_requests list
    chat_id = snap_requests.pop(0)

    try:
        asyncio.run_coroutine_threadsafe(
            send_photo_async(chat_id, img_bytes), telegram_event_loop)
    except Exception as e:
        print(f"Error scheduling coroutine: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the "start" command. It replies with the text "Hola".
    """
    id = update.message.from_user.id;
    await update.message.reply_text(f"Hola {id}")


async def snap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the "snap" command. If the user is allowed, then it
    forwards the command to the MQTT broker.
    """
    id = update.message.from_user.id
    print(f"{id}: Received 'snap' command request via Telegram")

    if (id not in allowed_users):
        print(f"user {id} isn't allowed to use this command")
    else:
        # ensure that the request is recorded and enqueued
        # in the same order
        async with enqueue_lock:
            snap_requests.append(update.message.chat_id)
            mqtt_client.publish(MQTT_TOPIC_CMD, "snap")

        await update.message.reply_text("Snap command sent!")


if __name__ == '__main__':
    with open("app_configuration.yaml", "r") as config_file:
        c_ = yaml.safe_load(config_file)

    # keep track of users who requested the snap
    snap_requests = []
    enqueue_lock = asyncio.Lock()

    # users that are allowed to call commands
    allowed_users = set(c_['telegram']['allowed_users'])

    # MQTT settings
    broker = urlparse(c_['mqtt']['broker_uri'])
    topics = c_['mqtt']['topics']
    MQTT_TOPIC_IMG = topics.get('images'  , '/camera/img')
    MQTT_TOPIC_CMD = topics.get('commands', '/camera/cmd')

    # Initialize MQTT client
    mqtt_client = mqtt.Client()
    mqtt_client.on_message = on_message
    mqtt_client.connect(broker.hostname, broker.port or 1883, 60)
    mqtt_client.subscribe(MQTT_TOPIC_IMG)
    mqtt_client.loop_start()

    telegram_event_loop = asyncio.get_event_loop()

    # Create the Telegram bot application
    app = ApplicationBuilder().token(c_['telegram']['token']).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snap", snap))
    app.run_polling()

    # Stop the MQTT client when done
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
