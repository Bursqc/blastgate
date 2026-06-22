Import("env")

def erase_flash_before_upload(source, target, env):
    # Resolve port and esptool path from PlatformIO environment
    upload_port = env.subst("$UPLOAD_PORT")
    esptool = env.subst("$ESPTOOLPY")

    print(f"Erasing flash on port {upload_port}...")

    env.Execute(
        env.VerboseAction(
            f'"{esptool}" --chip esp32 --port "{upload_port}" erase_flash',
            "Erasing entire flash (NVS, WiFi creds, all)..."
        )
    )

env.AddPreAction("upload", erase_flash_before_upload)
