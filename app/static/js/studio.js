/* Studio: ordinary text is rendered by the browser in the user's font, and
   only notation goes to the server.

   The distinction matters. The font is applied once with @font-face, so
   typing costs nothing. Notation is different: the parser lives in the
   backend and is not duplicated here, so each change asks /api/preview for
   the markup and drops it in. Debounced, because that is a request per
   keystroke otherwise. */

(function () {
  "use strict";

  var jobId = window.JOB_ID;
  var DEBOUNCE_MS = 250;

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

    fetch("/api/preview", {
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
})();
