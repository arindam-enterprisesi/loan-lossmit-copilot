import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DANIEL_CASE_ID, mockCases } from "@/mocks/data";
import { resetMockStore } from "@/mocks/store";
import { DocumentsWorkspace } from "./documents-workspace";
import { ReviewWorkspace } from "./review-workspace";

beforeEach(() => resetMockStore());

const daniel = mockCases.filter((c) => c.id === DANIEL_CASE_ID);

/**
 * The Day 3 done-when, end to end on the mock backend: Daniel's pay stub is uploaded, read, opened,
 * and a wrong value is corrected with a reason. Real clock, so it waits for the mock job (about 4 s).
 */
describe("upload, review and correct a pay stub", () => {
  it("goes from a file to a corrected value that keeps its original", async () => {
    // 1. Upload
    const upload = render(
      <DocumentsWorkspace cases={daniel} pillarSlug="underwriting" section="document-intelligence" />,
    );
    await screen.findByText("Documents for Daniel Reyes — purchase");
    const file = new File(["x"], "reyes_paystub_nov.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Choose files"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload 1" }));

    // 2. The new row appears while it is being read, then turns reviewable
    const row = () => screen.getByText("reyes_paystub_nov.pdf").closest("tr")!;
    await waitFor(() => expect(row()).toHaveTextContent("Processing"));
    await waitFor(() => expect(row().querySelector("a")).not.toBeNull(), { timeout: 8000 });
    expect(row()).toHaveTextContent("DI-CHK-02");
    const href = row().querySelector("a")!.getAttribute("href")!;
    const documentId = href.split("/").pop()!;
    expect(href).toBe(`/underwriting/document-intelligence/${DANIEL_CASE_ID}/${documentId}`);
    upload.unmount();

    // 3. Review: the flagged net pay is first, with its box on the page picture
    render(
      <ReviewWorkspace
        caseId={DANIEL_CASE_ID}
        documentId={documentId}
        backHref="/underwriting/document-intelligence"
      />,
    );
    await screen.findByText("Extracted fields");
    expect(await screen.findByAltText("Page 1")).toHaveAttribute("src", "/mock/paystub-p1.svg");
    expect(parseFloat(screen.getByTestId("evidence-box").style.top)).toBeCloseTo(40, 5);
    expect(screen.getByText("1 to look at")).toBeInTheDocument();

    // 4. Correct it: a reason is required, then the original is kept
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    fireEvent.change(screen.getByLabelText("Corrected value"), { target: { value: "2033.61" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(screen.getByText(/reason/i, { selector: "p" })).toBeInTheDocument(); // refused without one

    fireEvent.change(screen.getByLabelText("Why is the value being corrected?"), {
      target: { value: "OCR misread the last digit" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    expect(await screen.findByText(/Originally read as/)).toBeInTheDocument();
    expect(screen.getByText("2,083.61").tagName).toBe("S");
    expect(screen.getByText("2,033.61")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Nothing flagged")).toBeInTheDocument());
    expect(screen.getByText("Reviewed")).toBeInTheDocument();
  }, 20000);
});
