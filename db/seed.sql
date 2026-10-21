-- seed.sql -- deterministic demo scenario for `make demo`.
-- Embeddings here are SYNTHETIC topic vectors so the matching demo is
-- reproducible with no model loaded. The real pipeline overwrites
-- project_extractions.embedding with sentence-transformers output.

CREATE OR REPLACE FUNCTION fn_topic_vector(topic INT, jitter NUMERIC DEFAULT 0)
RETURNS vector AS $$
    SELECT ('[' || array_to_string(ARRAY(
        SELECT CASE
                 WHEN i = topic     THEN round(1.0 - jitter, 4)
                 WHEN i = topic + 1 THEN round(0.30 + jitter, 4)
                 WHEN i = topic + 2 THEN round(0.15 + jitter / 2, 4)
                 ELSE round((sin(i * 0.7 + topic) * 0.02)::numeric, 4)
               END
          FROM generate_series(0, 383) AS i
    ), ',') || ']')::vector
$$ LANGUAGE sql IMMUTABLE;

-- topic bands: education=0, healthcare=40, water=80, environment=120, livelihood=160

INSERT INTO ngos (name, registration_no, sector, state, established_year) VALUES
  ('Vidya Foundation',        'NGO-EDU-0001', 'education',        'Rajasthan',   2009),
  ('Gramin Shiksha Trust',    'NGO-EDU-0002', 'education',        'Bihar',       2014),
  ('Arogya Health Mission',   'NGO-HLT-0001', 'healthcare',       'Maharashtra', 2005),
  ('Jal Seva Samiti',         'NGO-WAT-0001', 'water_sanitation', 'Rajasthan',   2011),
  ('Prakriti Collective',     'NGO-ENV-0001', 'environment',      'Karnataka',   2016),
  ('Udyam Livelihood Board',  'NGO-LIV-0001', 'livelihood',       'Odisha',      2012);

INSERT INTO companies (name, cin, fy, avg_net_profit, mandated_csr_budget) VALUES
  ('Meridian Industries Ltd', 'L27100MH2001PLC000111', 'FY24-25', 450000000.00, 9000000.00),
  ('Kalpataru Motors Ltd',    'L34100TN1998PLC000222', 'FY24-25', 820000000.00, 16400000.00),
  ('Sundar Textiles Ltd',     'L17110GJ2005PLC000333', 'FY24-25', 120000000.00, 2400000.00);

INSERT INTO projects (ngo_id, title, proposal_text, sector, state, requested_amount, duration_months, num_phases, status) VALUES
  (1, 'Rural school attendance drive, Barmer',
      'Vidya Foundation has worked with government primary schools in Barmer district, Rajasthan since 2009. Attendance in our 40 partner schools averages 61%, and in the harvest months many classrooms are half empty. Over 12 months we will serve a hot midday meal in every school, train teachers in activity-based methods, and build a network of community mobilisers who visit families when a child stops coming. The programme reaches about 11,000 primary school children. Our goal is to raise average attendance from 61% to 69%. We request Rs 24 lakh, covering meals, teacher workshops and mobiliser stipends.',
      'education', 'Rajasthan', 2400000.00, 12, 3, 'approved'),
  (2, 'Digital classrooms for Gaya block',
      'Gramin Shiksha Trust proposes to set up 25 smart classrooms with offline content servers in government middle schools of Gaya district, Bihar. Students in grades 6-8 here score an average of 48% in the block-level learning assessment. With digital lessons, teacher support and weekly practice tests, we aim to lift that average to 57% within 9 months. The project will reach 3,200 students. The total cost is Rs 18,00,000, mainly for equipment, content licences and teacher training.',
      'education', 'Bihar', 1800000.00, 9, 3, 'approved'),
  (3, 'Maternal health outreach, Vidarbha',
      'Arogya Health Mission runs mobile health camps across 60 villages of Yavatmal district in Vidarbha, Maharashtra. Only 54% of pregnant women in these villages complete the recommended antenatal visits. Over 18 months our doctors and nurses will hold monthly camps, offer full antenatal check-ups, and screen every expectant mother for anaemia, with iron supplements and follow-up. We expect to reach 4,500 pregnant women and raise antenatal coverage to 72%. We are seeking Rs 32 lakh.',
      'healthcare', 'Maharashtra', 3200000.00, 18, 4, 'approved'),
  (4, 'Village handpump rehabilitation',
      'Jal Seva Samiti will repair 180 broken handpumps in 45 villages of Jaisalmer district, Rajasthan, and set up regular chlorination of every repaired source. Around 26,000 village residents depend on these pumps, and waterborne illness affects 18% of households each year. Our target is to bring that down to 12% within 10 months, through repairs, chlorine dosing and village water committees that keep the pumps running. The budget requested is Rs 15 lakh.',
      'water_sanitation', 'Rajasthan', 1500000.00, 10, 3, 'approved'),
  (5, 'Western Ghats reforestation',
      'Prakriti Collective works on degraded slopes in Uttara Kannada district, Karnataka. Over 24 months we will raise and plant 80,000 native saplings with local self-help groups, protect them from grazing, and monitor their survival every quarter. The aim is to restore 320 hectares of tree cover. We request Rs 28 lakh for nursery stock, field staff and survival monitoring.',
      'environment', 'Karnataka', 2800000.00, 24, 4, 'approved'),
  (6, 'Weaver cooperative market access',
      'Udyam Livelihood Board supports 900 handloom weavers in Bargarh district, Odisha, whose incomes have fallen as middlemen take a larger share. Over 15 months we will build a digital market linkage that connects weavers directly with buyers, run design training so products suit urban markets, and offer small inventory loans. We aim to increase household monthly income by 22%. The project requires Rs 21 lakh.',
      'livelihood', 'Odisha', 2100000.00, 15, 3, 'approved'),
  (1, 'Library expansion programme',
      'We wish to add reading rooms to 12 schools in Rajasthan so that children have books and a quiet place to read. The project will run for 6 months. We request Rs 9 lakh. The budget breakdown is not fully specified at submission time and will be shared later.',
      'education', 'Rajasthan', 900000.00, 6, 2, 'flagged'),
  (4, 'Sanitation block construction',
      'Jal Seva Samiti proposes to construct 60 community toilet blocks in villages of Rajasthan over 12 months. All construction will be handled by a single supplier we have worked with before, and invoices will be raised in round amounts per block. The total cost is Rs 42 lakh. Beneficiary numbers and current sanitation coverage will be assessed after work begins.',
      'water_sanitation', 'Rajasthan', 4200000.00, 12, 3, 'flagged');

-- NLP module output (synthetic for the demo scenario)
INSERT INTO project_extractions
  (project_id, goals, target_metric, beneficiaries, geography, sdgs, sdg_confidence,
   canonical_text, embedding, model_version, prompt_version) VALUES
  (1, '["raise primary school attendance","train teachers","mobilise community"]',
      '{"name":"attendance_rate","unit":"percentage_points","baseline":61,"target":69}',
      '{"count":11000,"group":"primary school children"}',
      '{"state":"Rajasthan","district":"Barmer","rural_urban":"rural"}',
      ARRAY[4], '{"4":0.96}',
      'education attendance rural primary school teacher training Rajasthan',
      fn_topic_vector(0, 0.00), 'seed-placeholder', 'v1'),
  (2, '["deploy smart classrooms","improve learning outcomes"]',
      '{"name":"learning_outcome_score","unit":"percentage_points","baseline":48,"target":57}',
      '{"count":3200,"group":"students grades 6-8"}',
      '{"state":"Bihar","district":"Gaya","rural_urban":"rural"}',
      ARRAY[4,9], '{"4":0.93,"9":0.61}',
      'education digital classroom learning outcomes Bihar students',
      fn_topic_vector(0, 0.08), 'seed-placeholder', 'v1'),
  (3, '["antenatal checkup coverage","anaemia screening"]',
      '{"name":"antenatal_coverage","unit":"percentage_points","baseline":54,"target":72}',
      '{"count":4500,"group":"pregnant women"}',
      '{"state":"Maharashtra","district":"Yavatmal","rural_urban":"rural"}',
      ARRAY[3,5], '{"3":0.97,"5":0.58}',
      'healthcare maternal antenatal anaemia screening Maharashtra women',
      fn_topic_vector(40, 0.00), 'seed-placeholder', 'v1'),
  (4, '["rehabilitate handpumps","reduce waterborne disease"]',
      '{"name":"disease_incidence","unit":"percent_reduction","baseline":18,"target":12}',
      '{"count":26000,"group":"village residents"}',
      '{"state":"Rajasthan","district":"Jaisalmer","rural_urban":"rural"}',
      ARRAY[6,3], '{"6":0.98,"3":0.64}',
      'water sanitation handpump chlorination waterborne disease Rajasthan',
      fn_topic_vector(80, 0.00), 'seed-placeholder', 'v1'),
  (5, '["plant native saplings","monitor survival"]',
      '{"name":"canopy_cover","unit":"hectares","baseline":0,"target":320}',
      '{"count":null,"group":"degraded forest land"}',
      '{"state":"Karnataka","district":"Uttara Kannada","rural_urban":"rural"}',
      ARRAY[13,15], '{"13":0.91,"15":0.95}',
      'environment reforestation native saplings canopy Karnataka',
      fn_topic_vector(120, 0.00), 'seed-placeholder', 'v1'),
  (6, '["digital market linkage","design training"]',
      '{"name":"weaver_income","unit":"percent_increase","baseline":0,"target":22}',
      '{"count":900,"group":"handloom weavers"}',
      '{"state":"Odisha","district":"Bargarh","rural_urban":"rural"}',
      ARRAY[8,1], '{"8":0.94,"1":0.70}',
      'livelihood weaver cooperative market linkage income Odisha',
      fn_topic_vector(160, 0.00), 'seed-placeholder', 'v1'),
  (7, '["expand school libraries"]', NULL,
      '{"count":null,"group":"school children"}',
      '{"state":"Rajasthan","district":null,"rural_urban":"rural"}',
      ARRAY[4], '{"4":0.72}',
      'education library reading room Rajasthan',
      fn_topic_vector(0, 0.25), 'seed-placeholder', 'v1'),
  (8, '["construct sanitation blocks"]', NULL,
      '{"count":null,"group":"village residents"}',
      '{"state":"Rajasthan","district":null,"rural_urban":"rural"}',
      ARRAY[6], '{"6":0.88}',
      'water sanitation toilet block construction Rajasthan',
      fn_topic_vector(80, 0.20), 'seed-placeholder', 'v1');

INSERT INTO impact_predictions
  (project_id, metric_name, metric_unit, predicted_value, ci_low, ci_high, impact_norm, model_version) VALUES
  (1, 'attendance_rate',    'percentage_points',  8.20,  5.10, 11.40, 0.8200, 'seed-placeholder'),
  (2, 'learning_outcome',   'percentage_points',  6.40,  3.20,  9.90, 0.6400, 'seed-placeholder'),
  (3, 'antenatal_coverage', 'percentage_points', 15.30, 11.00, 19.80, 0.9100, 'seed-placeholder'),
  (4, 'disease_incidence',  'percent_reduction',  5.80,  2.90,  8.60, 0.7300, 'seed-placeholder'),
  (5, 'canopy_cover',       'hectares',         290.00,210.00,340.00, 0.6900, 'seed-placeholder'),
  (6, 'weaver_income',      'percent_increase',  18.40, 12.10, 24.00, 0.7700, 'seed-placeholder'),
  (7, 'attendance_rate',    'percentage_points',  2.10,  0.40,  4.90, 0.2100, 'seed-placeholder'),
  (8, 'disease_incidence',  'percent_reduction',  3.20,  0.80,  6.10, 0.3200, 'seed-placeholder');

INSERT INTO fraud_scores (project_id, ngo_id, anomaly_score, is_anomaly, model_version) VALUES
  (1, 1, 0.1200, false, 'seed-placeholder'),
  (2, 2, 0.1800, false, 'seed-placeholder'),
  (3, 3, 0.0900, false, 'seed-placeholder'),
  (4, 4, 0.2200, false, 'seed-placeholder'),
  (5, 5, 0.1400, false, 'seed-placeholder'),
  (6, 6, 0.1900, false, 'seed-placeholder'),
  (7, 1, 0.4100, false, 'seed-placeholder'),
  (8, 4, 0.8700, true,  'seed-placeholder');

-- composite = 0.45*impact + 0.30*(1-fraud) + 0.15*sdg_conf + 0.10*track_record
INSERT INTO risk_grades
  (project_id, impact_norm, fraud_score, sdg_confidence, ngo_track_record, composite_score, grade, decision) VALUES
  (1, 0.8200, 0.1200, 0.9600, 0.8000, 0.8354, 'A', 'approved'),
  (2, 0.6400, 0.1800, 0.9300, 0.7000, 0.7220, 'B', 'approved'),
  (3, 0.9100, 0.0900, 0.9700, 0.8500, 0.8885, 'A', 'approved'),
  (4, 0.7300, 0.2200, 0.9800, 0.7500, 0.7639, 'B', 'approved'),
  (5, 0.6900, 0.1400, 0.9500, 0.7200, 0.7538, 'B', 'approved'),
  (6, 0.7700, 0.1900, 0.9400, 0.7400, 0.7714, 'B', 'approved'),
  (7, 0.2100, 0.4100, 0.7200, 0.8000, 0.4634, 'D', 'flagged'),
  (8, 0.3200, 0.8700, 0.8800, 0.7500, 0.4359, 'D', 'flagged');

INSERT INTO csr_rulebooks
  (company_id, fy, requirement_text, focus_areas, preferred_states, target_sdgs, min_budget, max_budget, embedding) VALUES
  (1, 'FY24-25',
   'We want to fund education projects that improve rural school attendance in northern India.',
   ARRAY['education'], ARRAY['Rajasthan','Bihar'], ARRAY[4], 500000.00, 5000000.00,
   fn_topic_vector(0, 0.02)),
  (2, 'FY24-25',
   'Priority is community health access for women in underserved districts.',
   ARRAY['healthcare'], ARRAY[]::TEXT[], ARRAY[3], 1000000.00, 8000000.00,
   fn_topic_vector(40, 0.02)),
  (3, 'FY24-25',
   'Clean water and sanitation infrastructure in water-stressed regions.',
   ARRAY['water_sanitation'], ARRAY['Rajasthan'], ARRAY[6], 500000.00, 3000000.00,
   fn_topic_vector(80, 0.02));

-- NGO spending history: features for the fraud model. NGO 4 carries the injected anomaly.
INSERT INTO ngo_spending_history
  (ngo_id, fy, total_spend, admin_expense_ratio, burn_rate_vs_schedule, category_mix_drift,
   round_number_freq, vendor_concentration, report_latency_days, cost_per_beneficiary, is_anomalous_truth) VALUES
  (1,'FY22-23', 1900000.00, 0.0800, 0.9800, 0.0400, 0.1000, 0.2200,  6,  180.00, false),
  (1,'FY23-24', 2200000.00, 0.0900, 1.0200, 0.0600, 0.1200, 0.2500,  8,  195.00, false),
  (2,'FY22-23', 1400000.00, 0.1100, 0.9500, 0.0700, 0.1500, 0.3000, 11,  410.00, false),
  (2,'FY23-24', 1650000.00, 0.1000, 1.0100, 0.0500, 0.1300, 0.2800,  9,  430.00, false),
  (3,'FY22-23', 2900000.00, 0.0700, 1.0000, 0.0300, 0.0900, 0.1900,  5,  620.00, false),
  (3,'FY23-24', 3100000.00, 0.0750, 0.9900, 0.0350, 0.1100, 0.2000,  7,  640.00, false),
  (4,'FY22-23', 1300000.00, 0.1200, 0.9700, 0.0800, 0.1800, 0.3500, 14,   52.00, false),
  (4,'FY23-24', 3900000.00, 0.3800, 1.8500, 0.4200, 0.7600, 0.9100, 48,  164.00, true),
  (5,'FY22-23', 2400000.00, 0.0900, 0.9600, 0.0500, 0.1400, 0.2600, 10, 1200.00, false),
  (5,'FY23-24', 2700000.00, 0.0950, 1.0300, 0.0450, 0.1200, 0.2400,  9, 1150.00, false),
  (6,'FY22-23', 1800000.00, 0.1300, 0.9400, 0.0900, 0.1600, 0.3200, 13, 2100.00, false),
  (6,'FY23-24', 2050000.00, 0.1250, 1.0000, 0.0700, 0.1400, 0.3100, 12, 2200.00, false);

-- Golden path: Meridian funds the Barmer attendance project through the real
-- transactional function, so phases, milestones and the ledger are all populated
-- by the triggers rather than by hand.
SELECT fn_commit_funds(1, 1, NULL, 2400000.00);

-- Phase 1 verified -> trigger releases the first tranche.
UPDATE milestones
   SET verification_status = 'verified', verified_by = 'seed', verified_at = now(),
       reported_at = now(), reported_metric = 3.10
 WHERE commitment_id = 1 AND phase_no = 1;

-- Monthly progress feeding the window-function views.
INSERT INTO impact_reports (project_id, period_month, metric_value) VALUES
  (1, DATE '2026-03-01', 1.20),
  (1, DATE '2026-04-01', 2.05),
  (1, DATE '2026-05-01', 3.10),
  (1, DATE '2026-06-01', 4.40),
  (1, DATE '2026-07-01', 5.60),
  (1, DATE '2026-08-01', 6.90);
