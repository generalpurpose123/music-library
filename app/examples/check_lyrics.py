from mutagen.id3 import ID3


audio_tags = ID3("coldplay_vivalavida.mp3")
if "USLT" in audio_tags:
    print("Lyrics found:")
    print(audio_tags["USLT"].text)
else:
    print("No lyrics frame found.")
