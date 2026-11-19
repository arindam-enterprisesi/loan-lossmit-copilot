/** Error thrown by the API layer (real or mock) so screens can react to the HTTP status. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** 409 from the field review endpoint: someone else changed the value since it was loaded. */
export function isEditConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}
