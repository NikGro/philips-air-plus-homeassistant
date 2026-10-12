# v1.1.0 — PureProtect 3200i über die Air+-Cloud

Dieser Release verbindet die Home-Assistant-Einrichtung mit der tatsächlich
verwendeten Air+-Geräteliste. In v1.0.x wurde weiterhin nur die alte
DaConnect-Schnittstelle abgefragt: Ein in Air+ vorhandener Purifier konnte dadurch
in der Geräteauswahl fehlen. Der neue Cloud-Weg erkennt den PureProtect 3200i,
der in der Cloud auch als **AC3220/10, Typ Unicorn** auftaucht.

### Neu

- **Air+ cloud: email + verification code** ist der empfohlene Einrichtungsweg.
  Anmeldung per E-Mail-Code und Auswahl des verknüpften Geräts, ohne manuelle ID.
- Automatische Token-Erneuerung und MQTT-Verbindungen über die regionalen
  AWS-IoT-Zugangsdaten. Jeder Wiederverbindungsversuch erhält eine frische
  signierte URL; Ausfälle werden mit zunehmendem Abstand erneut versucht.
- Ein/Aus und Betriebsmodi über das bestätigte Unicorn-Shadow-Protokoll.
  Power und Lüfterstufe verwenden jetzt ihre getrennten, richtigen Register.
- PM2.5, Allergenindex, Lüfterstufe und Filterlebensdauer aus gemeldeten Werten.
- Gemeldete Gerätezustände bestimmen die Anzeige. Eine reine Befehlsbestätigung
  wird nicht als tatsächlich ausgeführte Zustandsänderung angezeigt.
- Eigene Cloud-Option, Wiederanmeldung beim ursprünglichen Konto und sauberes
  Beenden der Verbindung beim Entladen oder Neuladen.

### Aktualisierung

**HACS aktualisieren → Home Assistant neu starten → Philips Air+ hinzufügen →
Air+ cloud: email + verification code auswählen.** Eine erfolglose alte
DaConnect-Konfiguration bitte entfernen und über diesen neuen Weg erneut
anlegen. Bestehende funktionierende DaConnect-Einträge behalten ihren Backend-Weg.
Es ist keine zusätzliche App auf dem PC erforderlich.

### Prüfung und Grenzen

Cloud-Anmeldung, Geräteauflistung und MQTT-Metadaten wurden mit dem Windows-Test
bestätigt. Ein echter Cloud-Shadow wurde lesend empfangen. Die automatisierten
Tests unter Home Assistant 2026.10.1 prüfen Einrichtung, Authentifizierung,
Token-Erneuerung, MQTT-Status und Wiederverbindungen sowie das Entity-Mapping.
Die vollständige Steuerung und der längere Betrieb in einer echten HA-Installation
müssen noch praktisch bestätigt werden. Filter-Reset und Standby-Schalter werden
für Unicorn bis zur Protokollbestätigung nicht angeboten. Kein Firmware-Flash
oder Geräte-Reset wird ausgeführt.
