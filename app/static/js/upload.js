/* Upload screen: three slots, then POST /api/jobs.

   The files keep whatever names they arrived with - the server decides page
   order from the field each one was sent in, so renaming here would be at
   best pointless and at worst misleading. */

(function () {
  "use strict";

  var chosen = { 1: null, 2: null, 3: null };
  var form = document.getElementById("upload-form");
  var buildButton = document.getElementById("build");
  var errorBox = document.getElementById("upload-error");
  var errorTitle = document.getElementById("upload-error-title");
  var errorDetail = document.getElementById("upload-error-detail");

  var MAX_BYTES = 10 * 1024 * 1024;

  function refresh() {
    buildButton.disabled = !(chosen[1] && chosen[2] && chosen[3]);
  }

  function showError(title, detail) {
    errorTitle.textContent = title;
    errorDetail.textContent = detail || "";
    errorDetail.classList.toggle("hidden", !detail);
    errorBox.classList.remove("hidden");
    errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function clearError() {
    errorBox.classList.add("hidden");
  }

  function attach(slot) {
    var number = Number(slot.dataset.slot);
    var input = slot.querySelector('input[type="file"]');
    var placeholder = slot.querySelector(".placeholder");
    var thumb = slot.querySelector(".thumb");
    var fileRow = slot.querySelector(".slot-file");
    var filename = slot.querySelector(".filename");

    function clear() {
      chosen[number] = null;
      input.value = "";
      thumb.classList.add("hidden");
      thumb.removeAttribute("src");
      placeholder.classList.remove("hidden");
      fileRow.classList.add("hidden");
      slot.classList.remove("filled", "invalid");
      refresh();
    }

    input.addEventListener("change", function () {
      var file = input.files[0];
      if (!file) {
        clear();
        return;
      }
      if (file.size > MAX_BYTES) {
        slot.classList.add("invalid");
        showError(
          "Page " + number + " is too large",
          "Each page must be under 10 MB. This one is " +
            (file.size / 1024 / 1024).toFixed(1) +
            " MB."
        );
        input.value = "";
        return;
      }

      clearError();
      chosen[number] = file;
      filename.textContent = file.name;
      fileRow.classList.remove("hidden");
      placeholder.classList.add("hidden");
      thumb.src = URL.createObjectURL(file);
      thumb.classList.remove("hidden");
      slot.classList.add("filled");
      slot.classList.remove("invalid");
      refresh();
    });

    slot.querySelector(".remove").addEventListener("click", clear);
  }

  Array.prototype.forEach.call(document.querySelectorAll(".slot"), attach);

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearError();
    buildButton.disabled = true;
    buildButton.textContent = "Uploading…";

    var payload = new FormData();
    payload.append("page_1", chosen[1]);
    payload.append("page_2", chosen[2]);
    payload.append("page_3", chosen[3]);

    fetch("/api/jobs", { method: "POST", body: payload })
      .then(function (response) {
        return response.json().then(function (body) {
          return { status: response.status, body: body };
        });
      })
      .then(function (result) {
        if (result.status === 202 && result.body.job_id) {
          window.location.href = "/build/" + result.body.job_id;
          return;
        }
        showError(titleFor(result.status), result.body.error);
        buildButton.disabled = false;
        buildButton.textContent = "Build My Font";
      })
      .catch(function () {
        showError(
          "We could not reach the server",
          "Check your connection and try again."
        );
        buildButton.disabled = false;
        buildButton.textContent = "Build My Font";
      });
  });

  function titleFor(status) {
    if (status === 422) return "Your handwriting page could not be validated.";
    if (status === 400 || status === 413) return "Please check your uploaded files.";
    if (status === 503) return "The font-building service is temporarily unavailable.";
    return "Something went wrong while building your font. Please try again.";
  }

  window.__uploadTitleFor = titleFor;
  refresh();
})();
