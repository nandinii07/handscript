/* The one thing to edit when the backend moves.

   Every other file in this frontend reads window.API_BASE rather than
   hardcoding a host, so pointing this static site at a real deployed
   backend later is a one-line change here, not a rewrite of the JS.

   No trailing slash. */
window.API_BASE = "http://localhost:8000";
