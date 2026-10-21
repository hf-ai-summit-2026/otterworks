require 'rails_helper'

RSpec.describe Api::V1::Admin::AnnouncementsController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    let!(:announcements) { create_list(:announcement, 3) }

    it 'returns all announcements' do
      get :index
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['announcements'].length).to eq(3)
    end

    it 'filters by status' do
      create(:announcement, :published)
      get :index, params: { status: 'published' }
      body = response.parsed_body
      expect(body['announcements'].all? { |a| a['status'] == 'published' }).to be true
    end
  end

  describe 'POST #create' do
    let(:valid_params) do
      { announcement: { title: 'System Update', body: 'Scheduled maintenance', severity: 'info' } }
    end

    it 'creates a new announcement' do
      expect do
        post :create, params: valid_params
      end.to change(Announcement, :count).by(1)
      expect(response).to have_http_status(:created)
    end

    it 'returns errors for invalid params' do
      post :create, params: { announcement: { title: '' } }
      expect(response).to have_http_status(:unprocessable_content)
    end
  end

  describe 'PUT #update' do
    let(:announcement) { create(:announcement) }

    it 'updates the announcement' do
      put :update, params: { id: announcement.id, announcement: { status: 'published' } }
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['status']).to eq('published')
    end
  end

  describe 'DELETE #destroy' do
    let!(:announcement) { create(:announcement) }

    it 'deletes the announcement' do
      expect do
        delete :destroy, params: { id: announcement.id }
      end.to change(Announcement, :count).by(-1)
      expect(response).to have_http_status(:no_content)
    end
  end
end
