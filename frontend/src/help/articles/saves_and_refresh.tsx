import type { Article } from "../help_types";
import { Callout, Pair, Symptoms, hostedPart } from "../help_kit";

const article: Article = {
  intro: (
    <>
      <p>
        Every change is saved to your account, and then the projection recalculates. These are two
        steps, and either one can fail on its own. A failed save keeps your draft open until you
        save it again or discard it. A saved change that couldn’t be recalculated stays saved.
      </p>
    </>
  ),
  sections: [
    {
      id: "save-status",
      title: "What the save status means",
      body: (
        <>
          <p>
            The planner’s header shows one status line: <strong>Saving…</strong> while a change is
            in flight, then <strong>Saved</strong> with the time of the last confirmed save. If a
            save fails, the line turns into the reason. Plan details save as you leave each field;
            other editors save when you submit them.
          </p>
          <p>The failure message tells you which of two cases you’re in:</p>
          <Pair
            left={{
              title: "“… was not saved”",
              body: (
                <p>
                  The server refused the change, for example because a value was out of range, your
                  session expired or the plan is read-only. Nothing changed. Correct the draft and
                  save again.
                </p>
              ),
            }}
            right={{
              title: "“… could not be confirmed”",
              body: (
                <p>
                  The connection dropped, timed out or the server failed before answering. The
                  change may or may not have been saved. Check the saved item before retrying so you
                  don’t apply it twice.
                </p>
              ),
            }}
          />
        </>
      ),
    },
    {
      id: "your-draft",
      title: "What happens to your draft",
      body: (
        <>
          <p>
            After a failed save the editor stays open with your entries and the note “Your draft is
            kept.” Closing it asks you to confirm that you want to discard the draft, and leaving
            the page asks too.
          </p>
          <Callout kind="boundary">
            {hostedPart(
              "saves-and-refresh.draft-lifetime",
              <p>
                A draft lives only in the open page. Reloading or closing the tab discards it; it
                isn’t stored on the device or the server.
              </p>,
            )}
          </Callout>
        </>
      ),
    },
    {
      id: "conflicts",
      title: "When a save conflicts with newer data",
      body: (
        <>
          <p>
            If the same item changed since you opened it, for example in another tab
            {hostedPart("saves-and-refresh.iphone", "")}, CoastMath doesn’t overwrite it or merge
            silently. It refuses the save and asks you to review.
          </p>
          <ul>
            <li>
              <strong>Expenses.</strong> Choose <strong>Review latest saved values</strong> to see
              the saved value and your draft for each field you changed, then{" "}
              <strong>Save my reviewed changes</strong>, <strong>Use saved version</strong> or{" "}
              <strong>Back to my draft</strong>. Fields you didn’t touch are never overwritten.
            </li>
            <li>
              <strong>Income allocation.</strong> Your rules are saved as one list, so a save
              replaces every rule, including ones added from Tax tools. After a conflict the panel
              shows <strong>Review the latest saved rules</strong>. Choose{" "}
              <strong>Keep my draft after reviewing these rules</strong> and save again, or{" "}
              <strong>Use latest rules and discard my draft</strong>.
            </li>
          </ul>
        </>
      ),
    },
    {
      id: "projection-refresh",
      title: "When a save worked but results didn’t update",
      body: (
        <>
          <p>
            After each saved change the projection clears and recalculates. If the recalculation
            fails, the status still reads <strong>Saved</strong>, an error appears briefly at the
            top of the sidebar, and the charts show no projection. Your change is kept.
          </p>
          <p>
            Reload the page to recalculate; don’t submit the change again. If the projection fails
            again, the error usually names an input it can’t use, such as a planning age earlier
            than the start of the plan. Undo or correct that input.
            {hostedPart("saves-and-refresh.no-clear-cause", "")}
          </p>
        </>
      ),
    },
    {
      id: "read-only-plans",
      title: "Read-only plans",
      body: (
        <>
          {hostedPart(
            "saves-and-refresh.read-only",
            <p>An archived plan is read-only until you restore it.</p>,
          )}
        </>
      ),
    },
    {
      id: "symptoms",
      title: "Common symptoms",
      body: (
        <>
          <Symptoms
            rows={[
              {
                symptom: "The status line shows an error in red",
                check: "Whether it says “was not saved” or “could not be confirmed”",
                next: "Correct and resave, or check the saved item first before retrying.",
              },
              ...hostedPart("saves-and-refresh.session-expired-symptom", [
                {
                  symptom: "“Your session expired”",
                  check: "Whether CoastMath opened in a new tab still shows your plans",
                  next: "Keep the editor open; once the new tab shows your plans, retry the save.",
                },
              ]),
              {
                symptom: "“Conflicts with saved data”",
                check: `Recent edits in another tab${hostedPart("saves-and-refresh.iphone", "")}`,
                next: "Review the latest saved values, then choose which to keep.",
              },
              {
                symptom: "Status says Saved, but charts show no projection",
                check: "The error at the top of the sidebar",
                next: "Reload the page. Correct the input the error names.",
              },
              ...hostedPart("saves-and-refresh.edit-window-symptom", []),
              ...hostedPart("saves-and-refresh.iphone-symptom", []),
            ]}
          />
          {hostedPart("saves-and-refresh.contact-support", null)}
        </>
      ),
    },
  ],
};
export default article;
