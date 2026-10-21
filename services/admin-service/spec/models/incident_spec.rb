require 'rails_helper'

RSpec.describe Incident do
  include ActiveSupport::Testing::TimeHelpers

  describe 'validations' do
    subject { build(:incident) }

    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_inclusion_of(:status).in_array(described_class::STATUSES) }
    it { is_expected.to validate_inclusion_of(:affected_service).in_array(described_class::AFFECTED_SERVICES) }

    it 'allows a blank affected_service' do
      expect(build(:incident, affected_service: nil)).to be_valid
    end
  end

  describe 'scopes' do
    let!(:open_incident) { create(:incident, severity: 'high') }
    let!(:investigating) { create(:incident, :investigating, severity: 'low') }
    let!(:resolved) { create(:incident, :resolved, severity: 'high') }
    let!(:closed) { create(:incident, :closed) }

    it '.active returns open and investigating incidents' do
      expect(described_class.active).to contain_exactly(open_incident, investigating)
    end

    it '.by_status filters by status' do
      expect(described_class.by_status('resolved')).to contain_exactly(resolved)
    end

    it '.by_severity filters by severity' do
      expect(described_class.by_severity('high')).to contain_exactly(open_incident, resolved)
    end
  end

  describe '#can_transition_to?' do
    {
      'open' => { allowed: %w[investigating resolved], denied: %w[open closed] },
      'investigating' => { allowed: %w[resolved], denied: %w[open investigating closed] },
      'resolved' => { allowed: %w[closed], denied: %w[open investigating resolved] },
      'closed' => { allowed: [], denied: %w[open investigating resolved closed] }
    }.each do |from, rules|
      rules[:allowed].each do |to|
        it "allows #{from} -> #{to}" do
          expect(build(:incident, status: from).can_transition_to?(to)).to be(true)
        end
      end

      rules[:denied].each do |to|
        it "denies #{from} -> #{to}" do
          expect(build(:incident, status: from).can_transition_to?(to)).to be(false)
        end
      end
    end

    it 'denies unknown target statuses' do
      expect(build(:incident).can_transition_to?('bogus')).to be(false)
    end
  end

  describe 'transition methods' do
    it '#investigate! moves an open incident to investigating' do
      incident = create(:incident)
      incident.investigate!
      expect(incident.reload.status).to eq('investigating')
    end

    it '#resolve! sets status and resolved_at' do
      incident = create(:incident, :investigating)
      freeze_time do
        incident.resolve!
        expect(incident.reload).to have_attributes(status: 'resolved', resolved_at: Time.current)
      end
    end

    it '#close! sets status and closed_at' do
      incident = create(:incident, :resolved)
      freeze_time do
        incident.close!
        expect(incident.reload).to have_attributes(status: 'closed', closed_at: Time.current)
      end
    end

    it 'raises InvalidTransitionError and leaves the record unchanged on an invalid transition' do
      incident = create(:incident, :closed)
      expect { incident.investigate! }
        .to raise_error(Incident::InvalidTransitionError, "Cannot transition from 'closed' to 'investigating'")
      expect(incident.reload.status).to eq('closed')
    end
  end

  describe '#active?' do
    it 'is true for open and investigating incidents' do
      expect(build(:incident)).to be_active
      expect(build(:incident, :investigating)).to be_active
    end

    it 'is false for resolved and closed incidents' do
      expect(build(:incident, :resolved)).not_to be_active
      expect(build(:incident, :closed)).not_to be_active
    end
  end

  describe 'Devin session predicates' do
    it 'reports no session when devin_session_id is blank' do
      incident = build(:incident)
      expect(incident.has_devin_session?).to be(false)
      expect(incident.has_active_devin_session?).to be(false)
    end

    it 'reports an active session when the session is running' do
      incident = build(:incident, :with_running_session)
      expect(incident.has_devin_session?).to be(true)
      expect(incident.has_active_devin_session?).to be(true)
    end

    it 'reports an inactive session when the session is not running' do
      incident = build(:incident, :with_running_session, devin_session_status: 'finished')
      expect(incident.has_devin_session?).to be(true)
      expect(incident.has_active_devin_session?).to be(false)
    end
  end
end
