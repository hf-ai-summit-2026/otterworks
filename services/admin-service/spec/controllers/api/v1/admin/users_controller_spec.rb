require 'rails_helper'

RSpec.describe Api::V1::Admin::UsersController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    let!(:users) { create_list(:admin_user, 3) }

    it 'returns paginated user list' do
      get :index
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['users'].length).to eq(3)
      expect(body['total']).to eq(3)
    end

    it 'filters by role' do
      create(:admin_user, :admin)
      get :index, params: { role: 'admin' }
      body = response.parsed_body
      expect(body['users'].all? { |u| u['role'] == 'admin' }).to be true
    end

    it 'filters by status' do
      create(:admin_user, :suspended)
      get :index, params: { status: 'suspended' }
      body = response.parsed_body
      expect(body['users'].all? { |u| u['status'] == 'suspended' }).to be true
    end

    it 'searches by query' do
      user = create(:admin_user, email: 'searchable@test.com')
      get :index, params: { q: 'searchable' }
      body = response.parsed_body
      expect(body['users'].any? { |u| u['id'] == user.id }).to be true
    end
  end

  describe 'GET #show' do
    let(:user) { create(:admin_user) }

    it 'returns user details' do
      get :show, params: { id: user.id }
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['id']).to eq(user.id)
      expect(body['email']).to eq(user.email)
    end

    it 'returns 404 for missing user' do
      get :show, params: { id: SecureRandom.uuid }
      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'PUT #update' do
    let(:user) { create(:admin_user) }

    it 'updates user attributes' do
      put :update, params: { id: user.id, user: { display_name: 'New Name' } }
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['display_name']).to eq('New Name')
    end

    it 'returns errors for invalid params' do
      put :update, params: { id: user.id, user: { role: 'invalid_role' } }
      expect(response).to have_http_status(:unprocessable_content)
    end
  end

  describe 'DELETE #destroy' do
    let(:user) { create(:admin_user) }

    it 'soft-deletes the user' do
      delete :destroy, params: { id: user.id }
      expect(response).to have_http_status(:no_content)
      expect(user.reload.status).to eq('deleted')
    end
  end

  describe 'PUT #suspend' do
    let(:user) { create(:admin_user) }

    it 'suspends the user' do
      put :suspend, params: { id: user.id, reason: 'Policy violation' }
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['status']).to eq('suspended')
    end
  end

  describe 'PUT #activate' do
    let(:user) { create(:admin_user, :suspended) }

    it 'activates the user' do
      put :activate, params: { id: user.id }
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['status']).to eq('active')
    end
  end
end
