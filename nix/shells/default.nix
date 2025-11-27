{
  python311,
  python311Packages,
  mkShell,
}:
mkShell {
  buildInputs = [
    python311
    python311Packages.requests
    python311Packages.google-api-python-client
    python311Packages.google-auth-oauthlib
    python311Packages.pytz
    python311Packages.beautifulsoup4
  ];

  shellHook = ''
    echo "Welcome to the development shell for Lublin District Council Scraper!"
    echo "You can run the scraper using: python3 scrape.py"
    echo "You can upload events to Google Calendar with: python3 main.py"
  '';
}
