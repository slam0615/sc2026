export interface BasicInfo {
  unitName: string;
  taxId: string;
  city: string;
  district: string;
  unitType: string;
  unitTypeOther: string; // If 'Other' is selected
  schoolType: string; // Public/Private
  hospitalType: string; // Public/Private
  industry: string;
  employeesMale: number;
  employeesFemale: number;
  scale: string; // Calculated
  contactName: string;
  contactDept: string;
  contactTitle: string;
  contactPhone: string;
  contactEmail: string;
}

export interface Question {
  id: number;
  partId: number;
  partTitle: string;
  questionText: string;
  note?: string; // The red text
  points: number;
}

export interface CategoryResult {
  partId: number;
  title: string;
  score: number;
  totalPoints: number;
  percentage: number;
}

export enum Tabs {
  INTRO = 'intro',
  BASIC_INFO = 'basic_info',
  QUESTIONNAIRE = 'questionnaire',
  RESULT = 'result'
}
