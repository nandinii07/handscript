/* Progress screen: poll the job, show the stage it is actually in.

   No percentages. The API reports queued, processing, completed or failed,
   and that is all this shows - a made-up progress bar would be a lie about
   something that takes two seconds.

   Adapted from app/static/js/build.js for static hosting: the job id comes
   from the URL's query string (?job=<id>) instead of a server-injected
   window.JOB_ID, since this page has no server behind it to inject anything,
   and the backend call goes through window.API_BASE. */

(function () {
  "use strict";

  var jobId = new URLSearchParams(window.location.search).get("job");
  var stages = document.getElementById("stages");
  var headline = document.getElementById("headline");
  var subhead = document.getElementById("subhead");
  var errorBox = document.getElementById("build-error");
  var errorTitle = document.getElementById("build-error-title");
  var errorDetail = document.getElementById("build-error-detail");
  var doneActions = document.getElementById("done-actions");
  var failActions = document.getElementById("fail-actions");
  var studioLink = document.getElementById("studio-link");

  if (!jobId) {
    headline.textContent = "No job to show";
    subhead.textContent = "Start again from the upload page.";
    failActions.classList.remove("hidden");
    return;
  }

  function mark(name, state) {
    var item = stages.querySelector('[data-stage="' + name + '"]');
    if (!item) return;
    item.classList.remove("done", "active");
    if (state) item.classList.add(state);
    var symbol = item.querySelector(".mark");
    if (state === "done") symbol.textContent = "✓";
    else if (state === "active") symbol.innerHTML = '<span class="spinner"></span>';
    else symbol.textContent = "";
  }

  function apply(payload) {
    if (payload.status === "queued") {
      mark("validating", "active");
    } else if (payload.status === "processing") {
      mark("validating", "done");
      mark("building", "active");
    } else if (payload.status === "completed") {
      ["validating", "building", "finalising"].forEach(function (name) {
        mark(name, "done");
      });
      headline.textContent = "Your handwriting font is ready.";
      subhead.textContent = "Open the studio to try it out and download it.";
      studioLink.href = "studio.html?job=" + jobId;
      doneActions.classList.remove("hidden");
      return true;
    } else if (payload.status === "failed") {
      mark("validating", null);
      mark("building", null);
      headline.textContent = "We could not build your font";
      subhead.textContent = "Nothing was saved. You can fix the pages and try again.";
      errorTitle.textContent = titleFor(payload.error_type);
      errorDetail.textContent = payload.error || "";
      errorBox.classList.remove("hidden");
      failActions.classList.remove("hidden");
      return true;
    }
    return false;
  }

  function titleFor(errorType) {
    if (errorType === "PageValidationError" || errorType === "SheetDetectionError") {
      return "Your handwriting page could not be validated.";
    }
    if (errorType === "PotraceNotFound" || errorType === "FontForgeNotFound") {
      return "The font-building service is temporarily unavailable.";
    }
    if (errorType === "ValueError" || errorType === "FileNotFoundError") {
      return "Please check your uploaded files.";
    }
    return "Something went wrong while building your font. Please try again.";
  }

  function poll() {
    fetch(window.API_BASE + "/api/jobs/" + jobId)
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        if (!apply(payload)) window.setTimeout(poll, 500);
      })
      .catch(function () {
        window.setTimeout(poll, 1500);
      });
  }

  mark("validating", "active");
  poll();
})();
