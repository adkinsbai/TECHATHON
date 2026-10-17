import styles from '../data/reference-styles.json';
export type ReferenceStyle = keyof typeof styles;
export const REFERENCE_STYLES = styles;
export function readReferenceStyle(value: unknown): ReferenceStyle { return typeof value === 'string' && Object.hasOwn(styles, value) ? value as ReferenceStyle : 'preserve'; }
