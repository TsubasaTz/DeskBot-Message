#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// -------------------- Configuration --------------------

const char* WIFI_SSID = "WIFI NAME HERE";
const char* WIFI_PASSWORD = "WIFI PASSWORD HERE";
//const char* WS_HOST = "TO BE UPDATED";
//const uint16_t WS_PORT = TO BE UPDATED;

const char* WS_PATH = "/";

//const int DEVICE_NUMBER = NUMBER ASSIGNED TO THE DEVICE;
//const char* DEVICE_TOKEN = "DEVICE TOKEN GOES HERE";

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_ADDRESS 0x3C
#define OLED_RESET -1

Adafruit_SSD1306 display(
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    &Wire,
    OLED_RESET
);

WebSocketsClient webSocket;

bool wifiWasConnected = false;
bool oledReady = false;
unsigned long lastWifiAttempt = 0;


void displayMessage(const String& message) {
    if (!oledReady) {
        return;
    }

    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setTextWrap(true);

    display.setCursor(0, 0);
    display.println("DeskBot Message");
    display.drawLine(0, 12, 127, 12, SSD1306_WHITE);

    display.setCursor(0, 18);
    display.println(message);

    display.display();
}

// -------------------- Device registration --------------------

void registerDevice() {
    JsonDocument registration;

    registration["device"] = DEVICE_NUMBER;
    registration["token"] = DEVICE_TOKEN;

    String payload;
    serializeJson(registration, payload);

    webSocket.sendTXT(payload);

    Serial.print("Registration sent for device #");
    Serial.println(DEVICE_NUMBER);
}

// -------------------- Incoming WebSocket messages --------------------

void handleWebSocketEvent(
    WStype_t type,
    uint8_t* payload,
    size_t length
) {
    switch (type) {
        case WStype_CONNECTED:
            Serial.println("WebSocket connected.");

            displayMessage("Server connected!\nRegistering device...");

            registerDevice();
            break;

        case WStype_DISCONNECTED:
            Serial.println("WebSocket disconnected.");

            displayMessage("Server disconnected.\nReconnecting...");
            break;

        case WStype_TEXT: {
            String incoming;
            incoming.reserve(length);

            for (size_t i = 0; i < length; i++) {
                incoming += static_cast<char>(payload[i]);
            }

            Serial.print("Received: ");
            Serial.println(incoming);

            JsonDocument document;

            DeserializationError error =
                deserializeJson(document, incoming);

            if (error) {
                Serial.println("Invalid JSON received.");
                return;
            }

            const char* messageType =
                document["type"] | "";

            if (strcmp(messageType, "registered") == 0) {
                Serial.println("Device authentication successful.");

                displayMessage("Connected!\nWaiting for messages...");
            }

            else if (strcmp(messageType, "message") == 0) {
                const char* text =
                    document["message"] | "";

                Serial.println("Displaying Discord message.");

                displayMessage(String(text));
            }

            else if (strcmp(messageType, "error") == 0) {
                Serial.println("Device registration failed.");

                displayMessage("Registration failed.\nCheck device token.");
            }

            break;
        }

        case WStype_ERROR:
            Serial.println("WebSocket error.");
            break;

        default:
            break;
    }
}

// -------------------- Setup --------------------

void setup() {
    Serial.begin(115200);
    delay(300);

    Wire.begin(21, 22);

    oledReady = display.begin(
        SSD1306_SWITCHCAPVCC,
        OLED_ADDRESS
    );

    if (!oledReady) {
        Serial.println("OLED initialization failed.");
    } else {
        displayMessage("Starting DeskBot...");
    }

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Connecting to Wi-Fi");

    while (WiFi.status() != WL_CONNECTED) {
        delay(300);
        Serial.print(".");
    }

    Serial.println();
    Serial.print("Wi-Fi connected. ESP32 IP: ");
    Serial.println(WiFi.localIP());

    displayMessage("Wi-Fi connected!\nConnecting to Mac...");

    webSocket.onEvent(handleWebSocketEvent);
    webSocket.setReconnectInterval(5000);

    webSocket.begin(WS_HOST, WS_PORT, WS_PATH);

    Serial.print("Connecting to WebSocket server at ");
    Serial.print(WS_HOST);
    Serial.print(":");
    Serial.println(WS_PORT);
}

// -------------------- Main loop --------------------

void loop() {
    webSocket.loop();

    if (WiFi.status() != WL_CONNECTED) {
        if (wifiWasConnected) {
            wifiWasConnected = false;

            Serial.println("Wi-Fi disconnected.");
            displayMessage("Wi-Fi disconnected...");
        }

        if (millis() - lastWifiAttempt >= 5000) {
            lastWifiAttempt = millis();
            WiFi.reconnect();
        }
    } else if (!wifiWasConnected) {
        wifiWasConnected = true;

        Serial.println("Wi-Fi connected.");
    }

    delay(5);
}
