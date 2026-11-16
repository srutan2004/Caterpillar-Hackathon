// Physical unit conversions only; every domain interval arrives from /api/bootstrap in seconds.
export const MS_PER_SECOND = 1000;

export const secondsToMs = (seconds: number): number => seconds * MS_PER_SECOND;
