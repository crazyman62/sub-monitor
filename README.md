# Emby User Manager

A Dockerized Python Flask application designed to manage Emby users. This application allows you to supplement standard Emby user data with custom fields (like Package details, Facebook and PayPal info) and provides an automated expiry engine to disable accounts when subscriptions lapse.

## Features

- **Automated Expiry**: Automatically disables users in Emby when their `Expiry Date` passes.
- **Custom User Details**: Track First Name, Last Name, Email, Packages (VOD, IPTV, VOD & IPTV), PayPal, and Facebook info.
- **Payer Relationships**: Map which users pay for other users.
- **Background Sync**: Runs an hourly background task to sync users from Emby and update their status.
- **Light/Dark Mode**: Clean Bootstrap 5 interface that supports a toggleable dark mode.
- **Dockerized**: Easy to deploy via `docker-compose`, making it perfect for TrueNAS, Unraid, or standard Linux servers. Data is persisted in a local SQLite volume.

## Quick Start (Docker)

1. Clone this repository.
2. Edit the `docker-compose.yml` to set your desired `SECRET_KEY` and `TZ` (Timezone).
3. Bring the container up:
   ```bash
   docker-compose up -d
   ```
4. Access the web interface at `http://<your-server-ip>:5005`.
5. Go to the **Settings** page in the UI to enter your Emby Server URL (e.g., `http://192.168.1.10:8096`) and an API Key generated from your Emby Dashboard -> Advanced -> API Keys.
6. Click **Sync Now** on the Users page to pull down your Emby users.

## How Expiry Works

The application runs a background task using APScheduler every 1 hour. During this task:
1. It connects to Emby and syncs the user list.
2. It checks all locally stored users. If a user is NOT flagged as `Do Not Expire`, and their `Expiry Date` is in the past, the application uses the Emby API to set their `IsDisabled` policy to `true`.
3. Disabled users are marked with a red "Disabled" badge in the UI.

## Delete Functionality

When you delete a user from the web UI, you will be prompted with a confirmation dialog. Proceeding will attempt to permanently delete the user from your Emby server via API, and then delete their record from the local database.
