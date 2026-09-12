/* Studio: ordinary text is rendered by the browser in the user's font, and
   only notation goes to the server.

   The distinction matters. The font is applied once with @font-face, so
   typing costs nothing. Notation is different: the parser lives in the
   backend and is not duplicated here, so each change asks /api/preview for
   the markup and drops it in. Debounced, because that is a request per
   keystroke otherwise.

   Adapted from app/static/js/studio.js for static hosting. Two things the
   old server-rendered page did that this must now do itself, since there is
   no server behind this page to have done them first:
     - the job id comes from the URL's query string, not window.JOB_ID;
     - the "is this job actually finished?" gate (previously a server-side
       check that rendered not_ready.html instead of the studio page) is now
       a fetch on load, branching between #studio-not-ready and
       #studio-content. Everything below that point is unchanged. */

(function () {
  "use strict";

  var jobId = new URLSearchParams(window.location.search).get("job");
  var notReady = document.getElementById("studio-not-ready");
  var notReadyDetail = document.getElementById("not-ready-detail");
  var content = document.getElementById("studio-content");

  function showNotReady(message) {
    notReadyDetail.textContent = message;
    notReady.classList.remove("hidden");
    content.classList.add("hidden");
  }

  if (!jobId) {
    showNotReady("No font to show — start from the upload page.");
    return;
  }

  fetch(window.API_BASE + "/api/jobs/" + jobId)
    .then(function (response) {
      if (response.status === 404) {
        showNotReady("This font could not be found.");
        return null;
      }
      return response.json();
    })
    .then(function (job) {
      if (!job) return;
      if (job.status !== "completed") {
        document.getElementById("not-ready-back").href = "build.html?job=" + jobId;
        showNotReady("This font is still " + job.status + ".");
        return;
      }

      document.getElementById("family-name").textContent = job.family_name;
      document.getElementById("family-name-2").textContent = job.family_name;
      var downloadLink = document.getElementById("download-link");
      downloadLink.href = window.API_BASE + "/api/jobs/" + jobId + "/font.ttf";
      wireDownload(downloadLink, job.family_name);

      notReady.classList.add("hidden");
      content.classList.remove("hidden");
      initStudio();
    })
    .catch(function () {
      showNotReady("Could not reach the server to check this font.");
    });

  /* "Download My Font" normally just relies on the <a download> attribute -
     that's all a plain browser (including this same page deployed to
     Cloudflare) needs, and this function does nothing there.

     Inside the desktop app, `href` points across origins (this page is
     served from Tauri's own local protocol, the font from
     http://localhost:8000) - and WKWebView, the system webview this app
     uses on macOS, does not honour `download` on a cross-origin link the
     way a full browser does; it just navigates the window instead of
     saving anything. window.__TAURI__ (present only inside the desktop
     app - see tauri.conf.json's withGlobalTauri) is used here to fetch the
     font's bytes ourselves and hand them to a native Save panel instead,
     which sidesteps that webview limitation entirely. */
  function wireDownload(link, familyName) {
    if (!window.__TAURI__) return;

    link.addEventListener("click", function (event) {
      event.preventDefault();
      var suggestedName = (familyName || "handscript-font").replace(/\s+/g, "") + ".ttf";

      fetch(link.href)
        .then(function (response) {
          if (!response.ok) throw new Error("The server returned " + response.status);
          return response.arrayBuffer();
        })
        .then(function (bytes) {
          return window.__TAURI__.dialog
            .save({
              defaultPath: suggestedName,
              filters: [{ name: "TrueType Font", extensions: ["ttf"] }]
            })
            .then(function (path) {
              if (!path) return; // user cancelled the save panel
              return window.__TAURI__.fs.writeFile(path, new Uint8Array(bytes));
            });
        })
        .catch(function (error) {
          window.alert("Could not save the font: " + error.message);
        });
    });
  }

  function initStudio() {
    /* ---- plain text ---- */

    var textInput = document.getElementById("text-input");
    var textOutput = document.getElementById("text-output");

    function showText() {
      // textContent, not innerHTML: whatever is typed is text, not markup.
      textOutput.textContent = textInput.value;
    }

    textInput.addEventListener("input", showText);
    showText();

    var copyButton = document.getElementById("copy-text");
    if (copyButton) {
      copyButton.addEventListener("click", function () {
        var done = function () {
          copyButton.textContent = "Copied";
          window.setTimeout(function () {
            copyButton.textContent = "Copy my text";
          }, 1400);
        };
        if (navigator.clipboard) {
          navigator.clipboard.writeText(textInput.value).then(done, function () {});
        } else {
          textInput.select();
          document.execCommand("copy");
          done();
        }
      });
    }

    /* ---- notation ---- */

    var formulaInput = document.getElementById("formula-input");
    var formulaOutput = document.getElementById("formula-output");
    var errorBox = document.getElementById("formula-error");
    var errorDetail = document.getElementById("formula-error-detail");
    var missingBox = document.getElementById("formula-missing");
    var missingDetail = document.getElementById("formula-missing-detail");
    var timer = null;

    function requestPreview() {
      var text = formulaInput.value;

      fetch(window.API_BASE + "/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text, job_id: jobId })
      })
        .then(function (response) {
          return response.json().then(function (body) {
            return { status: response.status, body: body };
          });
        })
        .then(function (result) {
          if (result.status !== 200) {
            errorDetail.textContent =
              result.body.error || "The preview could not be produced.";
            errorBox.classList.remove("hidden");
            return;
          }

          var payload = result.body;

          if (payload.error) {
            // Bad notation is something you are in the middle of typing, not a
            // failure: the last good render stays on screen.
            errorDetail.textContent = payload.error;
            errorBox.classList.remove("hidden");
          } else {
            errorBox.classList.add("hidden");
            formulaOutput.innerHTML = payload.html || "";
          }

          if (payload.missing && payload.missing.length) {
            missingDetail.textContent =
              "Your font does not contain: " + payload.missing.join(" ");
            missingBox.classList.remove("hidden");
          } else {
            missingBox.classList.add("hidden");
          }
        })
        .catch(function () {
          errorDetail.textContent = "Could not reach the server for a preview.";
          errorBox.classList.remove("hidden");
        });
    }

    function schedulePreview() {
      window.clearTimeout(timer);
      timer = window.setTimeout(requestPreview, DEBOUNCE_MS);
    }

    var DEBOUNCE_MS = 250;

    formulaInput.addEventListener("input", schedulePreview);

    Array.prototype.forEach.call(
      document.querySelectorAll("#examples .chip"),
      function (chip) {
        chip.addEventListener("click", function () {
          formulaInput.value = chip.textContent.trim();
          requestPreview();
        });
      }
    );

    requestPreview();
  }
})();
