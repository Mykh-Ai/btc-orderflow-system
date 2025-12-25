# Buyer

Position planning and alerting module.

Consumes validated `PEAK` events from DeltaScout, calculates trade structure
(entry, stop-loss, take-profit levels), and sends formatted alerts to Telegram via n8n.

Example output:
see [`/docs/examples/buyer_alert.txt`](../docs/examples/buyer_alert.txt)


