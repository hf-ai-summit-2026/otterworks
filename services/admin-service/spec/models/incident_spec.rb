require 'rails_helper'

RSpec.describe Incident do
  def build_incident(attrs = {})
    described_class.new({ title: 'Gateway 5xx spike', description: 'Elevated error rate', severity: 'high',
                          status: 'open' }.merge(attrs))
  end

  describe 'validations' do
    subject { build_incident }

    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_inclusion_of(:status).in_array(described_class::STATUSES) }

    it 'allows a blank affected_service' do
      expect(build_incident(affected_service: nil)).to be_valid
    end

    it 'rejects an unknown affected_service' do
      expect(build_incident(affected_service: 'not-a-service')).not_to be_valid
    end
  end

  describe '#can_transition_to?' do
    it 'follows VALID_TRANSITIONS' do
      described_class::VALID_TRANSITIONS.each do |from, allowed|
        incident = build_incident(status: from)
        described_class::STATUSES.each do |to|
          expect(incident.can_transition_to?(to)).to eq(allowed.include?(to)), "#{from} -> #{to}"
        end
      end
    end
  end

  describe 'lifecycle transitions' do
    let(:incident) { build_incident.tap(&:save!) }

    it 'moves open -> investigating -> resolved -> closed and stamps timestamps' do
      incident.investigate!
      expect(incident.reload.status).to eq('investigating')

      incident.resolve!
      expect(incident.reload.status).to eq('resolved')
      expect(incident.resolved_at).to be_present

      incident.close!
      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'allows resolving directly from open' do
      incident.resolve!
      expect(incident.reload.status).to eq('resolved')
    end

    it 'raises InvalidTransitionError and leaves the record unchanged on an invalid transition' do
      expect { incident.close! }.to raise_error(Incident::InvalidTransitionError, /'open' to 'closed'/)
      expect(incident.reload.status).to eq('open')
      expect(incident.closed_at).to be_nil
    end

    it 'does not allow leaving the closed state' do
      incident.resolve!
      incident.close!
      expect { incident.investigate! }.to raise_error(Incident::InvalidTransitionError)
    end
  end

  describe '#active?' do
    it 'is true only for open and investigating' do
      active = described_class::STATUSES.select { |s| build_incident(status: s).active? }
      expect(active).to contain_exactly('open', 'investigating')
    end
  end

  describe '.active' do
    it 'returns only open and investigating incidents' do
      open = build_incident.tap(&:save!)
      investigating = build_incident(status: 'investigating').tap(&:save!)
      build_incident(status: 'resolved').tap(&:save!)

      expect(described_class.active).to contain_exactly(open, investigating)
    end
  end

  describe 'devin session helpers' do
    it 'reports no session when devin_session_id is blank' do
      incident = build_incident
      expect(incident).not_to have_devin_session
      expect(incident).not_to have_active_devin_session
    end

    it 'reports an active session only while running' do
      expect(build_incident(devin_session_id: 's-1', devin_session_status: 'running')).to have_active_devin_session
      finished = build_incident(devin_session_id: 's-1', devin_session_status: 'finished')
      expect(finished).to have_devin_session
      expect(finished).not_to have_active_devin_session
    end
  end
end
