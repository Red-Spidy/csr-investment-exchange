// Port of db/seed.sql (the rows inserted by hand). The golden-path commitment
// and its triggered rows are NOT listed here: demo.ts runs them through the
// engine, the same way the SQL seed runs them through fn_commit_funds.

import type { DbState } from './types'

export const SEED: DbState = {
  ngos: [
    { id: 1, name: 'Vidya Foundation',       registrationNo: 'NGO-EDU-0001', sector: 'education',        state: 'Rajasthan',   establishedYear: 2009 },
    { id: 2, name: 'Gramin Shiksha Trust',   registrationNo: 'NGO-EDU-0002', sector: 'education',        state: 'Bihar',       establishedYear: 2014 },
    { id: 3, name: 'Arogya Health Mission',  registrationNo: 'NGO-HLT-0001', sector: 'healthcare',       state: 'Maharashtra', establishedYear: 2005 },
    { id: 4, name: 'Jal Seva Samiti',        registrationNo: 'NGO-WAT-0001', sector: 'water_sanitation', state: 'Rajasthan',   establishedYear: 2011 },
    { id: 5, name: 'Prakriti Collective',    registrationNo: 'NGO-ENV-0001', sector: 'environment',      state: 'Karnataka',   establishedYear: 2016 },
    { id: 6, name: 'Udyam Livelihood Board', registrationNo: 'NGO-LIV-0001', sector: 'livelihood',       state: 'Odisha',      establishedYear: 2012 },
  ],

  companies: [
    { id: 1, name: 'Meridian Industries Ltd', cin: 'L27100MH2001PLC000111', fy: 'FY24-25', avgNetProfit: 450_000_000, mandatedBudget: 9_000_000,  committedBudget: 0 },
    { id: 2, name: 'Kalpataru Motors Ltd',    cin: 'L34100TN1998PLC000222', fy: 'FY24-25', avgNetProfit: 820_000_000, mandatedBudget: 16_400_000, committedBudget: 0 },
    { id: 3, name: 'Sundar Textiles Ltd',     cin: 'L17110GJ2005PLC000333', fy: 'FY24-25', avgNetProfit: 120_000_000, mandatedBudget: 2_400_000,  committedBudget: 0 },
  ],

  projects: [
    { id: 1, ngoId: 1, title: 'Rural school attendance drive, Barmer', sector: 'education', state: 'Rajasthan', requestedAmount: 2_400_000, durationMonths: 12, numPhases: 3, status: 'approved',
      proposalText: 'We propose to raise attendance across 40 government primary schools in Barmer district through midday meal support, teacher training and a community mobiliser network. Current average attendance is 61%.' },
    { id: 2, ngoId: 2, title: 'Digital classrooms for Gaya block', sector: 'education', state: 'Bihar', requestedAmount: 1_800_000, durationMonths: 9, numPhases: 3, status: 'approved',
      proposalText: 'Setting up 25 smart classrooms with offline content servers across Gaya. Target is improved learning outcomes for 3200 students in grades 6-8.' },
    { id: 3, ngoId: 3, title: 'Maternal health outreach, Vidarbha', sector: 'healthcare', state: 'Maharashtra', requestedAmount: 3_200_000, durationMonths: 18, numPhases: 4, status: 'approved',
      proposalText: 'Mobile health camps covering 60 villages, focused on antenatal checkups and anaemia screening for 4500 women.' },
    { id: 4, ngoId: 4, title: 'Village handpump rehabilitation', sector: 'water_sanitation', state: 'Rajasthan', requestedAmount: 1_500_000, durationMonths: 10, numPhases: 3, status: 'approved',
      proposalText: 'Repair and chlorination of 180 handpumps across 45 villages to reduce waterborne disease incidence.' },
    { id: 5, ngoId: 5, title: 'Western Ghats reforestation', sector: 'environment', state: 'Karnataka', requestedAmount: 2_800_000, durationMonths: 24, numPhases: 4, status: 'approved',
      proposalText: 'Planting 80000 native saplings with three-year survival monitoring across degraded slopes.' },
    { id: 6, ngoId: 6, title: 'Weaver cooperative market access', sector: 'livelihood', state: 'Odisha', requestedAmount: 2_100_000, durationMonths: 15, numPhases: 3, status: 'approved',
      proposalText: 'Building a digital market linkage for 900 handloom weavers, including design training and inventory financing.' },
    { id: 7, ngoId: 1, title: 'Library expansion programme', sector: 'education', state: 'Rajasthan', requestedAmount: 900_000, durationMonths: 6, numPhases: 2, status: 'flagged',
      proposalText: 'Adding reading rooms to 12 schools. Budget breakdown not fully specified at submission time.' },
    { id: 8, ngoId: 4, title: 'Sanitation block construction', sector: 'water_sanitation', state: 'Rajasthan', requestedAmount: 4_200_000, durationMonths: 12, numPhases: 3, status: 'flagged',
      proposalText: 'Construction of 60 toilet blocks. Vendor list concentrated on a single supplier with unusually round invoice amounts.' },
  ],

  // topic bands: education=0, healthcare=40, water=80, environment=120, livelihood=160
  extractions: [
    { projectId: 1, goals: ['raise primary school attendance', 'train teachers', 'mobilise community'],
      targetMetric: { name: 'attendance_rate', unit: 'percentage_points', baseline: 61, target: 69 },
      beneficiaries: { count: 11000, group: 'primary school children' },
      geography: { state: 'Rajasthan', district: 'Barmer', ruralUrban: 'rural' },
      sdgs: [4], sdgConfidence: { 4: 0.96 }, redFlags: [], topic: 0, jitter: 0, modelVersion: 'claude-opus-5', promptVersion: 'v1' },
    { projectId: 2, goals: ['deploy smart classrooms', 'improve learning outcomes'],
      targetMetric: { name: 'learning_outcome_score', unit: 'percentage_points', baseline: 48, target: 57 },
      beneficiaries: { count: 3200, group: 'students grades 6-8' },
      geography: { state: 'Bihar', district: 'Gaya', ruralUrban: 'rural' },
      sdgs: [4, 9], sdgConfidence: { 4: 0.93, 9: 0.61 }, redFlags: [], topic: 0, jitter: 0.08, modelVersion: 'claude-opus-5', promptVersion: 'v1' },
    { projectId: 3, goals: ['antenatal checkup coverage', 'anaemia screening'],
      targetMetric: { name: 'antenatal_coverage', unit: 'percentage_points', baseline: 54, target: 72 },
      beneficiaries: { count: 4500, group: 'pregnant women' },
      geography: { state: 'Maharashtra', district: 'Yavatmal', ruralUrban: 'rural' },
      sdgs: [3, 5], sdgConfidence: { 3: 0.97, 5: 0.58 }, redFlags: [], topic: 40, jitter: 0, modelVersion: 'claude-opus-5', promptVersion: 'v1' },
    { projectId: 4, goals: ['rehabilitate handpumps', 'reduce waterborne disease'],
      targetMetric: { name: 'disease_incidence', unit: 'percent_reduction', baseline: 18, target: 12 },
      beneficiaries: { count: 26000, group: 'village residents' },
      geography: { state: 'Rajasthan', district: 'Jaisalmer', ruralUrban: 'rural' },
      sdgs: [6, 3], sdgConfidence: { 6: 0.98, 3: 0.64 }, redFlags: [], topic: 80, jitter: 0, modelVersion: 'claude-opus-5', promptVersion: 'v1' },
    { projectId: 5, goals: ['plant native saplings', 'monitor survival'],
      targetMetric: { name: 'canopy_cover', unit: 'hectares', baseline: 0, target: 320 },
      beneficiaries: { count: null, group: 'degraded forest land' },
      geography: { state: 'Karnataka', district: 'Uttara Kannada', ruralUrban: 'rural' },
      sdgs: [13, 15], sdgConfidence: { 13: 0.91, 15: 0.95 }, redFlags: [], topic: 120, jitter: 0, modelVersion: 'claude-opus-5', promptVersion: 'v1' },
    { projectId: 6, goals: ['digital market linkage', 'design training'],
      targetMetric: { name: 'weaver_income', unit: 'percent_increase', baseline: 0, target: 22 },
      beneficiaries: { count: 900, group: 'handloom weavers' },
      geography: { state: 'Odisha', district: 'Bargarh', ruralUrban: 'rural' },
      sdgs: [8, 1], sdgConfidence: { 8: 0.94, 1: 0.7 }, redFlags: [], topic: 160, jitter: 0, modelVersion: 'claude-opus-5', promptVersion: 'v1' },
    { projectId: 7, goals: ['expand school libraries'], targetMetric: null,
      beneficiaries: { count: null, group: 'school children' },
      geography: { state: 'Rajasthan', district: null, ruralUrban: 'rural' },
      sdgs: [4], sdgConfidence: { 4: 0.72 }, redFlags: [], topic: 0, jitter: 0.25, modelVersion: 'claude-opus-5', promptVersion: 'v1' },
    { projectId: 8, goals: ['construct sanitation blocks'], targetMetric: null,
      beneficiaries: { count: null, group: 'village residents' },
      geography: { state: 'Rajasthan', district: null, ruralUrban: 'rural' },
      sdgs: [6], sdgConfidence: { 6: 0.88 }, redFlags: [], topic: 80, jitter: 0.2, modelVersion: 'claude-opus-5', promptVersion: 'v1' },
  ],

  impactPredictions: [
    { projectId: 1, metricName: 'attendance_rate',    metricUnit: 'percentage_points', predictedValue: 8.2,   ciLow: 5.1,   ciHigh: 11.4, impactNorm: 0.82, modelVersion: 'xgb-v1' },
    { projectId: 2, metricName: 'learning_outcome',   metricUnit: 'percentage_points', predictedValue: 6.4,   ciLow: 3.2,   ciHigh: 9.9,  impactNorm: 0.64, modelVersion: 'xgb-v1' },
    { projectId: 3, metricName: 'antenatal_coverage', metricUnit: 'percentage_points', predictedValue: 15.3,  ciLow: 11.0,  ciHigh: 19.8, impactNorm: 0.91, modelVersion: 'xgb-v1' },
    { projectId: 4, metricName: 'disease_incidence',  metricUnit: 'percent_reduction', predictedValue: 5.8,   ciLow: 2.9,   ciHigh: 8.6,  impactNorm: 0.73, modelVersion: 'xgb-v1' },
    { projectId: 5, metricName: 'canopy_cover',       metricUnit: 'hectares',          predictedValue: 290,   ciLow: 210,   ciHigh: 340,  impactNorm: 0.69, modelVersion: 'xgb-v1' },
    { projectId: 6, metricName: 'weaver_income',      metricUnit: 'percent_increase',  predictedValue: 18.4,  ciLow: 12.1,  ciHigh: 24.0, impactNorm: 0.77, modelVersion: 'xgb-v1' },
    { projectId: 7, metricName: 'attendance_rate',    metricUnit: 'percentage_points', predictedValue: 2.1,   ciLow: 0.4,   ciHigh: 4.9,  impactNorm: 0.21, modelVersion: 'xgb-v1' },
    { projectId: 8, metricName: 'disease_incidence',  metricUnit: 'percent_reduction', predictedValue: 3.2,   ciLow: 0.8,   ciHigh: 6.1,  impactNorm: 0.32, modelVersion: 'xgb-v1' },
  ],

  fraudScores: [
    { projectId: 1, ngoId: 1, anomalyScore: 0.12, isAnomaly: false, modelVersion: 'iforest-v1' },
    { projectId: 2, ngoId: 2, anomalyScore: 0.18, isAnomaly: false, modelVersion: 'iforest-v1' },
    { projectId: 3, ngoId: 3, anomalyScore: 0.09, isAnomaly: false, modelVersion: 'iforest-v1' },
    { projectId: 4, ngoId: 4, anomalyScore: 0.22, isAnomaly: false, modelVersion: 'iforest-v1' },
    { projectId: 5, ngoId: 5, anomalyScore: 0.14, isAnomaly: false, modelVersion: 'iforest-v1' },
    { projectId: 6, ngoId: 6, anomalyScore: 0.19, isAnomaly: false, modelVersion: 'iforest-v1' },
    { projectId: 7, ngoId: 1, anomalyScore: 0.41, isAnomaly: false, modelVersion: 'iforest-v1' },
    { projectId: 8, ngoId: 4, anomalyScore: 0.87, isAnomaly: true,  modelVersion: 'iforest-v1' },
  ],

  riskGrades: [
    { projectId: 1, impactNorm: 0.82, fraudScore: 0.12, sdgConfidence: 0.96, ngoTrackRecord: 0.80, compositeScore: 0.8354, grade: 'A', decision: 'approved' },
    { projectId: 2, impactNorm: 0.64, fraudScore: 0.18, sdgConfidence: 0.93, ngoTrackRecord: 0.70, compositeScore: 0.7220, grade: 'B', decision: 'approved' },
    { projectId: 3, impactNorm: 0.91, fraudScore: 0.09, sdgConfidence: 0.97, ngoTrackRecord: 0.85, compositeScore: 0.8885, grade: 'A', decision: 'approved' },
    { projectId: 4, impactNorm: 0.73, fraudScore: 0.22, sdgConfidence: 0.98, ngoTrackRecord: 0.75, compositeScore: 0.7639, grade: 'B', decision: 'approved' },
    { projectId: 5, impactNorm: 0.69, fraudScore: 0.14, sdgConfidence: 0.95, ngoTrackRecord: 0.72, compositeScore: 0.7538, grade: 'B', decision: 'approved' },
    { projectId: 6, impactNorm: 0.77, fraudScore: 0.19, sdgConfidence: 0.94, ngoTrackRecord: 0.74, compositeScore: 0.7714, grade: 'B', decision: 'approved' },
    { projectId: 7, impactNorm: 0.21, fraudScore: 0.41, sdgConfidence: 0.72, ngoTrackRecord: 0.80, compositeScore: 0.4634, grade: 'D', decision: 'flagged' },
    { projectId: 8, impactNorm: 0.32, fraudScore: 0.87, sdgConfidence: 0.88, ngoTrackRecord: 0.75, compositeScore: 0.4359, grade: 'D', decision: 'flagged' },
  ],

  rulebooks: [
    { id: 1, companyId: 1, fy: 'FY24-25', requirementText: 'We want to fund education projects that improve rural school attendance in northern India.',
      focusAreas: ['education'], preferredStates: ['Rajasthan', 'Bihar'], targetSdgs: [4], minBudget: 500_000, maxBudget: 5_000_000, topic: 0, jitter: 0.02 },
    { id: 2, companyId: 2, fy: 'FY24-25', requirementText: 'Priority is community health access for women in underserved districts.',
      focusAreas: ['healthcare'], preferredStates: [], targetSdgs: [3], minBudget: 1_000_000, maxBudget: 8_000_000, topic: 40, jitter: 0.02 },
    { id: 3, companyId: 3, fy: 'FY24-25', requirementText: 'Clean water and sanitation infrastructure in water-stressed regions.',
      focusAreas: ['water_sanitation'], preferredStates: ['Rajasthan'], targetSdgs: [6], minBudget: 500_000, maxBudget: 3_000_000, topic: 80, jitter: 0.02 },
  ],

  // NGO 4 carries the injected anomaly in FY23-24.
  spendingHistory: [
    { ngoId: 1, fy: 'FY22-23', totalSpend: 1_900_000, adminExpenseRatio: 0.08,   burnRateVsSchedule: 0.98, categoryMixDrift: 0.04,   roundNumberFreq: 0.10, vendorConcentration: 0.22, reportLatencyDays: 6,  costPerBeneficiary: 180 },
    { ngoId: 1, fy: 'FY23-24', totalSpend: 2_200_000, adminExpenseRatio: 0.09,   burnRateVsSchedule: 1.02, categoryMixDrift: 0.06,   roundNumberFreq: 0.12, vendorConcentration: 0.25, reportLatencyDays: 8,  costPerBeneficiary: 195 },
    { ngoId: 2, fy: 'FY22-23', totalSpend: 1_400_000, adminExpenseRatio: 0.11,   burnRateVsSchedule: 0.95, categoryMixDrift: 0.07,   roundNumberFreq: 0.15, vendorConcentration: 0.30, reportLatencyDays: 11, costPerBeneficiary: 410 },
    { ngoId: 2, fy: 'FY23-24', totalSpend: 1_650_000, adminExpenseRatio: 0.10,   burnRateVsSchedule: 1.01, categoryMixDrift: 0.05,   roundNumberFreq: 0.13, vendorConcentration: 0.28, reportLatencyDays: 9,  costPerBeneficiary: 430 },
    { ngoId: 3, fy: 'FY22-23', totalSpend: 2_900_000, adminExpenseRatio: 0.07,   burnRateVsSchedule: 1.00, categoryMixDrift: 0.03,   roundNumberFreq: 0.09, vendorConcentration: 0.19, reportLatencyDays: 5,  costPerBeneficiary: 620 },
    { ngoId: 3, fy: 'FY23-24', totalSpend: 3_100_000, adminExpenseRatio: 0.075,  burnRateVsSchedule: 0.99, categoryMixDrift: 0.035,  roundNumberFreq: 0.11, vendorConcentration: 0.20, reportLatencyDays: 7,  costPerBeneficiary: 640 },
    { ngoId: 4, fy: 'FY22-23', totalSpend: 1_300_000, adminExpenseRatio: 0.12,   burnRateVsSchedule: 0.97, categoryMixDrift: 0.08,   roundNumberFreq: 0.18, vendorConcentration: 0.35, reportLatencyDays: 14, costPerBeneficiary: 52 },
    { ngoId: 4, fy: 'FY23-24', totalSpend: 3_900_000, adminExpenseRatio: 0.38,   burnRateVsSchedule: 1.85, categoryMixDrift: 0.42,   roundNumberFreq: 0.76, vendorConcentration: 0.91, reportLatencyDays: 48, costPerBeneficiary: 164 },
    { ngoId: 5, fy: 'FY22-23', totalSpend: 2_400_000, adminExpenseRatio: 0.09,   burnRateVsSchedule: 0.96, categoryMixDrift: 0.05,   roundNumberFreq: 0.14, vendorConcentration: 0.26, reportLatencyDays: 10, costPerBeneficiary: 1200 },
    { ngoId: 5, fy: 'FY23-24', totalSpend: 2_700_000, adminExpenseRatio: 0.095,  burnRateVsSchedule: 1.03, categoryMixDrift: 0.045,  roundNumberFreq: 0.12, vendorConcentration: 0.24, reportLatencyDays: 9,  costPerBeneficiary: 1150 },
    { ngoId: 6, fy: 'FY22-23', totalSpend: 1_800_000, adminExpenseRatio: 0.13,   burnRateVsSchedule: 0.94, categoryMixDrift: 0.09,   roundNumberFreq: 0.16, vendorConcentration: 0.32, reportLatencyDays: 13, costPerBeneficiary: 2100 },
    { ngoId: 6, fy: 'FY23-24', totalSpend: 2_050_000, adminExpenseRatio: 0.125,  burnRateVsSchedule: 1.00, categoryMixDrift: 0.07,   roundNumberFreq: 0.14, vendorConcentration: 0.31, reportLatencyDays: 12, costPerBeneficiary: 2200 },
  ],

  commitments: [],
  phases: [],
  milestones: [],
  ledger: [],
  audit: [],
  impactReports: [],
  seq: { commitments: 0, phases: 0, milestones: 0, ledger: 0, audit: 0, impactReports: 0 },
}

/** Monthly progress for project 1, inserted by the seed after the golden path. */
export const SEED_IMPACT_REPORTS: [string, number][] = [
  ['2026-03-01', 1.2], ['2026-04-01', 2.05], ['2026-05-01', 3.1],
  ['2026-06-01', 4.4], ['2026-07-01', 5.6], ['2026-08-01', 6.9],
]
