import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/shared/toast";
import { UploadPanel } from "./upload-panel";

const api = vi.hoisted(() => ({
  uploadDocuments: vi.fn(),
  getJob: vi.fn(),
  USE_MOCKS: true, // the job polling hook reads this flag to pick its interval
}));
vi.mock("@/lib/api", () => api);

const pdf = (name = "paystub.pdf") => new File(["x"], name, { type: "application/pdf" });
const choose = (...files: File[]) =>
  fireEvent.change(screen.getByLabelText("Choose files"), { target: { files } });

beforeEach(() => {
  api.uploadDocuments.mockReset();
  api.getJob.mockReset();
});

describe("UploadPanel", () => {
  it("lists the chosen files and lets one be removed", () => {
    render(<UploadPanel caseId="c1" />);
    choose(pdf("a.pdf"), pdf("b.pdf"));
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove a.pdf" }));
    expect(screen.queryByText("a.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("b.pdf")).toBeInTheDocument();
  });

  it("refuses a file type the API would reject", () => {
    render(<UploadPanel caseId="c1" />);
    choose(new File(["x"], "notes.txt", { type: "text/plain" }));
    expect(screen.getByRole("alert")).toHaveTextContent("notes.txt");
    expect(screen.queryByRole("button", { name: /^Upload/ })).toBeDisabled();
  });

  it("uploads with the chosen type, shows progress, then reports the job finished", async () => {
    api.uploadDocuments.mockResolvedValue({
      documents: [],
      job: { id: "job-1", status: "queued", progress: 0 },
    });
    api.getJob.mockResolvedValue({ id: "job-1", status: "succeeded", progress: 1 });
    const onUploaded = vi.fn();
    const onJobFinished = vi.fn();

    render(<UploadPanel caseId="c1" onUploaded={onUploaded} onJobFinished={onJobFinished} />);
    choose(pdf());
    fireEvent.change(screen.getByLabelText("Document type"), { target: { value: "pay_stub" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload 1" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    expect(api.uploadDocuments).toHaveBeenCalledWith("c1", [expect.any(File)], "pay_stub");

    expect(await screen.findByText("1 file: Done")).toBeInTheDocument();
    await waitFor(() => expect(onJobFinished).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("shows the error as a message with Try again, and keeps the files, when the upload fails", async () => {
    api.uploadDocuments.mockRejectedValue(new Error("File too large"));
    render(
      <ToastProvider>
        <UploadPanel caseId="c1" />
      </ToastProvider>,
    );
    choose(pdf());
    fireEvent.click(screen.getByRole("button", { name: "Upload 1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("File too large");
    expect(screen.getByText("paystub.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("Try again sends the same files again, and the message goes away", async () => {
    api.uploadDocuments
      .mockRejectedValueOnce(new Error("Network down"))
      .mockResolvedValueOnce({ documents: [], job: { id: "job-1", status: "queued", progress: 0 } });
    api.getJob.mockResolvedValue({ id: "job-1", status: "succeeded", progress: 1 });
    const onUploaded = vi.fn();
    render(
      <ToastProvider>
        <UploadPanel caseId="c1" onUploaded={onUploaded} />
      </ToastProvider>,
    );
    choose(pdf());
    fireEvent.click(screen.getByRole("button", { name: "Upload 1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    expect(api.uploadDocuments).toHaveBeenCalledTimes(2);
    expect(api.uploadDocuments.mock.calls[1][1]).toHaveLength(1); // the one file that was waiting
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("cannot upload without a case", () => {
    render(<UploadPanel caseId={null} />);
    expect(screen.getByRole("button", { name: "Choose files" })).toBeDisabled();
  });
});
